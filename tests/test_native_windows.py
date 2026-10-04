"""Native Windows integration in temporary directories, without user setup."""

import json
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man import process_lock, self_update, storage
from agent_env_man.model import Error
from test_instructions import InstructionFixture


@unittest.skipUnless(os.name == "nt", "Native Windows process APIs")
class NativeProcesses(unittest.TestCase):
    def test_waiting_lock_acquires_after_native_owner_releases(self):
        with tempfile.TemporaryDirectory(prefix="aem-native-wait-") as folder:
            path = Path(folder)
            program = ("import sys; sys.path.insert(0,sys.argv[2]); from pathlib import Path; "
                       "from agent_env_man.process_lock import lock; "
                       "guard=lock(Path(sys.argv[1])); guard.__enter__(); "
                       "print('locked', flush=True); sys.stdin.read(1); "
                       "guard.__exit__(None,None,None)")
            child = subprocess.Popen([sys._base_executable, "-c", program, str(path),
                                      str(Path(process_lock.__file__).parents[1])],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            import concurrent.futures
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    self.assertEqual(executor.submit(child.stdout.readline).result(timeout=10), "locked\n")
                    with self.assertRaisesRegex(Error, "holds this config's lock"):
                        with process_lock.lock(path, timeout=0.1, error_type=Error, shared=True):
                            self.fail("Windows shared readers must still exclude another owner")
                    acquired = executor.submit(self._acquire_native_lock, path)
                    child.stdin.write("x")
                    child.stdin.flush()
                    self.assertTrue(acquired.result(timeout=10))
                self.assertEqual(child.wait(timeout=10), 0)
                self.assertEqual((path / "lock").read_bytes(), b"0")
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)

    @staticmethod
    def _acquire_native_lock(path):
        with process_lock.lock(path, timeout=5):
            return True

    def test_exception_releases_native_lock_and_preserves_persistent_file(self):
        with tempfile.TemporaryDirectory(prefix="aem-native-unwind-") as folder:
            path = Path(folder)
            with self.assertRaisesRegex(ValueError, "operation failed"):
                with process_lock.lock(path):
                    raise ValueError("operation failed")
            with process_lock.lock(path):
                self.assertTrue((path / "lock").exists())
            self.assertEqual((path / "lock").read_bytes(), b"0")

    def test_wait_for_already_exited_native_process(self):
        child = subprocess.Popen([sys._base_executable, "-c", "pass"])
        self.assertEqual(child.wait(timeout=10), 0)
        self.assertTrue(self_update.wait_for_parent(child.pid))

    def test_detached_worker_children_have_no_console_and_preserve_results(self):
        # Match the queued worker's console-less parent, rather than inheriting
        # the test runner's console and accidentally masking console allocation.
        child_code = 'import ctypes,sys; print(ctypes.windll.kernel32.GetConsoleWindow()); sys.exit(7)'
        program = ('import sys,json; sys.path.insert(0,sys.argv[1]); '
                   'from agent_env_man.self_update import run_captured,git; '
                   'result=run_captured([sys.executable,"-c",sys.argv[2]],capture_output=True,text=True,timeout=10); '
                   'print(json.dumps({"code":result.returncode,"stdout":result.stdout,"stderr":result.stderr,'
                   '"git":git("--version")}))')
        result = subprocess.run([sys._base_executable, '-c', program, str(Path(self_update.__file__).parents[1]), child_code],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
                                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        observation = json.loads(result.stdout)
        self.assertEqual(observation['code'], 7)
        self.assertEqual(observation['stdout'].strip(), '0')
        self.assertEqual(observation['stderr'], '')
        self.assertTrue(observation['git'].startswith('git version'))

    def test_terminated_owner_releases_lock_without_removing_lock_file(self):
        with tempfile.TemporaryDirectory(prefix="aem-native-crash-") as folder:
            path = Path(folder)
            program = ("import sys; sys.path.insert(0, sys.argv[2]); from pathlib import Path; "
                       "from agent_env_man.process_lock import lock; "
                       "guard = lock(Path(sys.argv[1])); guard.__enter__(); "
                       "print('locked', flush=True); sys.stdin.read(1)")
            # Launch the interpreter directly so kill() reaches the lock owner
            # rather than a Windows virtual-environment redirector.
            child = subprocess.Popen([sys._base_executable, "-c", program, str(path),
                                      str(Path(process_lock.__file__).parents[1])],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            try:
                # A bounded readiness handshake avoids timing assumptions and
                # leaves an unresponsive child available for cleanup.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as reader:
                    ready = reader.submit(child.stdout.readline)
                    try:
                        self.assertEqual(ready.result(timeout=10), "locked\n")
                        with self.assertRaisesRegex(RuntimeError, "holds this config's lock"):
                            with process_lock.lock(path):
                                self.fail("Entered while another process owned the lock")
                    finally:
                        child.kill()
                        child.wait(timeout=10)
                with process_lock.lock(path):
                    self.assertTrue((path / "lock").exists())
                self.assertEqual((path / "lock").read_bytes(), b"0")
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)

    def test_parent_wait_timeout_then_real_process_exit(self):
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read(1)"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        try:
            with patch.object(self_update, "TIMEOUT", 0):
                self.assertFalse(self_update.wait_for_parent(child.pid))
            child.stdin.write(b"x")
            child.stdin.flush()
            with patch.object(self_update, "TIMEOUT", 10):
                self.assertTrue(self_update.wait_for_parent(child.pid))
            self.assertEqual(child.wait(timeout=10), 0)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    def test_lock_excludes_another_process_and_is_released(self):
        with tempfile.TemporaryDirectory(prefix="aem-native-lock-") as folder:
            path = Path(folder)
            program = ("import sys; from pathlib import Path; "
                       "from agent_env_man.process_lock import lock; "
                       "with_lock = lock(Path(sys.argv[1])); with_lock.__enter__(); "
                       "with_lock.__exit__(None, None, None)")
            with process_lock.lock(path):
                child = subprocess.run([sys.executable, "-c", program, str(path)],
                                       capture_output=True, text=True, timeout=15)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn("holds this config's lock", child.stderr)
            child = subprocess.run([sys.executable, "-c", program, str(path)],
                                   capture_output=True, text=True, timeout=15)
            self.assertEqual(child.returncode, 0, child.stderr)


@unittest.skipUnless(os.name == "nt", "Native Windows junction payloads")
class NativePayloads(unittest.TestCase):
    def test_junction_is_rejected_without_copying_or_changing_external_contents(self):
        with tempfile.TemporaryDirectory(prefix="aem-native-junction-") as folder:
            root = Path(folder)
            outside = root / "external files"
            outside.mkdir()
            original = b"preserve external contents\n"
            (outside / "user.txt").write_bytes(original)
            payload = root / "payload"
            payload.mkdir()
            junction = payload / "redirect"
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J",
                                     str(junction), str(outside)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(storage.is_reparse(junction))
            for source in (junction, payload):
                with self.subTest(source=source):
                    destination = root / "copy"
                    with self.assertRaisesRegex(Error, "symlinks/junctions are unsupported"):
                        storage.copy_payload(source, destination)
                    self.assertFalse(destination.exists())
                    self.assertEqual((outside / "user.txt").read_bytes(), original)


@unittest.skipUnless(os.name == "nt", "Native PowerShell hook execution")
class NativeHook(InstructionFixture):
    def test_encoded_hook_executes_with_literal_config_path(self):
        self.configure()
        original = self.config
        self.config = self.root / "machine 'quoted' $name.toml"
        original.rename(self.config)
        self.run_cli("bootstrap")
        self.run_cli("apply")
        hook_file = self.agent / "hooks.json"
        hook = json.loads(hook_file.read_text())["hooks"]["SessionStart"][0]["hooks"][0]
        result = subprocess.run(hook["command"], cwd=self.external,
                                input='{"hook_event_name":"SessionStart"}',
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        metadata = json.loads(context.split("\n")[1])
        self.assertEqual(metadata["root"], str(self.bundle))
        self.assertEqual(metadata["entry"], str(self.bundle / "start.md"))
        self.assertNotIn("Read development/rules.md", context)

    def test_claude_hook_executes_and_preserves_failure_exit_code(self):
        self.configure()
        original = self.config
        self.config = self.root / "claude 'quoted' $name.toml"
        original.rename(self.config)
        claude = self.root / "claude home"
        document = tomlkit.parse(self.config.read_text())
        document['agents'] = {'claude': {'root': str(claude), 'skills': str(claude / 'skills')}}
        self.config.write_text(tomlkit.dumps(document))
        catalog = tomlkit.parse(self.catalog.read_text())
        del catalog['instructions']['personal']['install']['entry']
        self.catalog.write_text(tomlkit.dumps(catalog))
        self.run_cli('apply', '--agent', 'claude', '--item', 'personal:entry')
        group = json.loads((claude / 'settings.json').read_text())['hooks']['SessionStart'][0]
        command = group['hooks'][0]['command']
        result = subprocess.run(command, cwd=self.external, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        metadata = json.loads(result.stdout.splitlines()[1])
        self.assertEqual(metadata['entry'], str(self.bundle / 'start.md'))
        self.assertEqual(metadata['global_entry'], str(claude / 'CLAUDE.md'))
        (claude / 'CLAUDE.md').unlink()
        result = subprocess.run(command, cwd=self.external, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('lookup failed', result.stderr)

    def test_powershell_navigation_preserves_literal_paths_and_failed_location(self):
        from agent_env_man.setup import shell_block

        self.configure()
        relocated = self.root / "synced 'quoted' $name"
        self.external.rename(relocated)
        self.external = self.bundle = relocated
        self.run_cli("bootstrap", "--external", "personal=" + str(relocated))
        executable = Path(sys.executable).with_name("aem.exe")
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        body = shell_block("powershell", self.config, executable, executable.parent)[2]
        body += "\naem --config " + quote(self.config) + " locate personal --source --cd\n"
        body += "[Console]::WriteLine((Get-Location).Path)\n"
        body += "aem --config " + quote(self.config) + " locate missing --cd\n"
        body += "[Console]::WriteLine($LASTEXITCODE)\n[Console]::WriteLine((Get-Location).Path)\n"
        encoded = base64.b64encode(body.encode("utf-16le")).decode()
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.stdout.splitlines(), [str(relocated), "1", str(relocated)])
        self.assertIn("missing", result.stderr)
