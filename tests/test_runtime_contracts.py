"""Bootstrap code must work before third-party site packages are available."""
from process_support import run_hidden

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from agent_env_man import self_update


class StandaloneRuntime(unittest.TestCase):
    def test_installer_help_runs_without_site_packages(self):
        script = Path(__file__).parents[1] / "scripts/setup.py"
        with tempfile.TemporaryDirectory(prefix="aem-standalone-installer-") as directory:
            result = run_hidden([sys.executable, "-I", "-S", str(script), "--help"],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--automation", result.stdout)

    def test_copied_worker_rejects_stale_request_without_site_packages(self):
        with tempfile.TemporaryDirectory(prefix="aem-standalone-worker-") as directory:
            root = Path(directory).resolve()
            request_directory = root / "request"
            request_directory.mkdir()
            for name in ("self_update.py", "process_lock.py", "official_skills.py", "link_paths.py"):
                shutil.copyfile(Path(self_update.__file__).with_name(name), request_directory / name)
            config = root / "machine.toml"
            state = root / "machine.toml.state"
            state.mkdir()
            result_path = state / "self-update.json"
            previous = {"token": "new-request", "status": "queued"}
            result_path.write_text(json.dumps(previous), encoding="utf-8")
            request = {"config": str(config), "parent_pid": 0, "token": "stale-request",
                       "settings": {"tool_dir": str(root / "tools")}}
            request_path = request_directory / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            # -I removes script-directory imports, so explicitly allow only
            # the copied stdlib helpers; -S keeps all site packages disabled.
            program = ("import runpy, sys; from pathlib import Path; "
                       "sys.path.insert(0, str(Path(sys.argv[1]).parent)); "
                       "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')")
            result = run_hidden([sys.executable, "-I", "-S", "-c", program,
                                     str(request_directory / "self_update.py"), str(request_path)],
                                    cwd=root, input="", capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result_path.read_text(encoding="utf-8")), previous)
            self.assertFalse(request_directory.exists())
