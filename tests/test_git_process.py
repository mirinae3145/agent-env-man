"""Git deadlines and process failures must remain bounded and diagnosable."""

import signal
import subprocess
import unittest
from unittest.mock import Mock, patch

from agent_env_man.git_source import Git
from agent_env_man.model import Error


class GitProcess(unittest.TestCase):

    def test_expired_budget_does_not_start_another_process(self):
        git = Git()
        with patch("agent_env_man.git_source.time.monotonic", return_value=git.deadline), patch(
                "agent_env_man.git_source.subprocess.Popen") as launch:
            with self.assertRaisesRegex(Error, "timed out"):
                git.run(None, "status")
        launch.assert_not_called()

    def test_timeout_terminates_process_group_and_reaps_child(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = [subprocess.TimeoutExpired("git", 1), (b"", b"")]
        with patch("agent_env_man.git_source.subprocess.Popen", return_value=process) as launch, patch(
                "agent_env_man.git_source.os.killpg") as kill_group:
            with self.assertRaisesRegex(Error, "checkout may need inspection"):
                Git().run(None, "fetch")
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        kill_group.assert_called_once_with(process.pid, signal.SIGKILL)
        process.kill.assert_called_once_with()
        self.assertEqual(process.communicate.call_count, 2)

    def test_nonzero_exit_uses_stdout_when_stderr_is_empty(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (b"remote failure\n", b"")
        with patch("agent_env_man.git_source.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(Error, "Git fetch failed: remote failure"):
                Git().run(None, "fetch")

    def test_unchecked_failure_and_utf8_decoding_preserve_diagnostics(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (b"invalid \xff\n", b"error \xff\n")
        with patch("agent_env_man.git_source.subprocess.Popen", return_value=process):
            result = Git().run(None, "status", check=False)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "invalid \ufffd")
            self.assertEqual(result.stderr, "error \ufffd")
            with self.assertRaises(UnicodeDecodeError):
                Git().run(None, "status", check=False, strict_utf8=True)
