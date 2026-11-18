"""Preservation and recovery contracts exercised through catalog installations."""

import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from agent_env_man.git_source import Git
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, fingerprint, lock, observation
import test_skill_catalog as skill_tests


class Workflow(unittest.TestCase):
    setUp = skill_tests.SkillCatalog.setUp
    repository = skill_tests.SkillCatalog.repository
    git = skill_tests.SkillCatalog.git
    commit = skill_tests.SkillCatalog.commit
    save_catalog = skill_tests.SkillCatalog.save_catalog
    run_cli = skill_tests.SkillCatalog.run_cli
    require_links = skill_tests.SkillCatalog.require_links
    bootstrap = skill_tests.SkillCatalog.bootstrap
    copy_mode = skill_tests.SkillCatalog.copy_mode
    publish_skill_change = skill_tests.SkillCatalog.publish_skill_change

    def installed_copy(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        return self.destination / "report"

    def test_unmanaged_copy_requires_selection_and_retains_backup(self):
        self.copy_mode()
        self.bootstrap()
        target = self.destination / "report"
        target.mkdir(parents=True)
        (target / "mine.txt").write_text("Keep me", encoding="utf-8")
        self.run_cli("apply", code=1)
        self.run_cli("apply", "--replace", code=1)
        self.run_cli("apply", "--item", "report", "--replace")
        backups = list((Config(self.config).state_dir / "skill-backups").glob("report-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "mine.txt").read_text(), "Keep me")
        self.assertFalse(list(self.destination.glob("*.aem-backup-*")))

    def test_skill_update_backup_is_outside_discovery_and_cross_filesystem_safe(self):
        target = self.installed_copy()
        before = fingerprint(target)
        self.publish_skill_change()
        self.run_cli("update")
        replace = os.replace

        def same_filesystem_only(source, destination):
            if 'skill-backups' in Path(source).parts or 'skill-backups' in Path(destination).parts:
                raise OSError("cross-filesystem rename")
            return replace(source, destination)

        with patch("agent_env_man.manager.os.replace", side_effect=same_filesystem_only):
            self.run_cli("apply")
        backups = list((Config(self.config).state_dir / "skill-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(fingerprint(backups[0]), before)
        self.assertEqual(list(self.destination.rglob("SKILL.md")), [target / "SKILL.md"])

    def test_isolated_backup_recovery_preserves_backup_and_user_edits(self):
        target = self.installed_copy()
        state = State(Config(self.config).state_dir)
        backup = Config(self.config).state_dir / "skill-backups" / "report-test"
        backup.parent.mkdir(exist_ok=True)
        shutil.copytree(target, backup)
        before = observation(target)
        stage = target.with_name(".aem-stage-test")
        stage.mkdir()
        (stage / "SKILL.md").write_text("replacement", encoding="utf-8")
        after = observation(stage)
        state.data["pending"] = {"operation": "skill-replacement", "key": "report",
                                 "target": str(target), "backup": str(backup), "stage": str(stage),
                                 "before": before, "after": after}
        state.save()
        # An interruption before removing the original is recoverable too.
        self.run_cli("recover")
        self.assertEqual(observation(target), before)
        stage.mkdir()
        (stage / "SKILL.md").write_text("replacement", encoding="utf-8")
        state.save()
        shutil.rmtree(target)
        os.replace(stage, target)
        (target / "user.txt").write_text("keep", encoding="utf-8")
        self.run_cli("recover", code=1)
        self.assertEqual((target / "user.txt").read_text(), "keep")
        (target / "user.txt").unlink()
        replace = os.replace

        def same_filesystem_only(source, destination):
            if 'skill-backups' in Path(source).parts or 'skill-backups' in Path(destination).parts:
                raise OSError("cross-filesystem rename")
            return replace(source, destination)

        with patch("agent_env_man.manager.os.replace", side_effect=same_filesystem_only):
            self.run_cli("recover")
        self.assertEqual(observation(target), before)
        self.assertEqual(observation(backup), before)

    def test_matching_copy_adoption_and_local_additions(self):
        self.copy_mode()
        self.bootstrap()
        target = self.destination / "report"
        shutil.copytree(self.checkouts / ".aem-repositories/report/skills/report", target)
        self.run_cli("apply", code=1)
        self.run_cli("apply", "--item", "report", "--adopt")
        (target / "mine.txt").write_text("Mine", encoding="utf-8")
        self.run_cli("apply", code=1)
        self.assertEqual((target / "mine.txt").read_text(), "Mine")
        self.assertFalse(list(self.destination.glob("*.aem-backup-*")))

    def test_copy_status_distinguishes_source_and_target_edits(self):
        target = self.installed_copy()
        self.publish_skill_change()
        self.run_cli("update")
        self.assertEqual(self.run_cli("status")["items"][0]["status"], "stale")
        self.run_cli("apply")
        (target / "local.txt").write_text("local", encoding="utf-8")
        self.assertEqual(self.run_cli("status")["items"][0]["status"], "modified-locally")
        self.publish_skill_change()
        self.run_cli("update")
        self.assertEqual(self.run_cli("status")["items"][0]["status"], "conflict")
        self.run_cli("apply", code=1)
        shutil.rmtree(target)
        self.assertEqual(self.run_cli("status")["items"][0]["status"], "missing")

    def test_link_failure_preserves_unmanaged_directory(self):
        self.bootstrap()
        target = self.destination / "report"
        target.mkdir(parents=True)
        (target / "mine.txt").write_text("Mine", encoding="utf-8")
        with patch.object(Path, "symlink_to", side_effect=OSError("No privilege")):
            self.run_cli("apply", "--item", "report", "--replace", code=1)
        self.assertEqual((target / "mine.txt").read_text(), "Mine")
        self.assertFalse(list(self.destination.glob("*.aem-backup-*")))

    def test_detach_preserves_empty_directories_and_executable_bits(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        payload = self.checkouts / ".aem-repositories/report/skills/report"
        (payload / "empty").mkdir()
        (payload / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (payload / "run.sh").chmod(0o755)
        expected = fingerprint(payload)
        self.run_cli("detach", "report")
        self.assertFalse(list(self.destination.glob("*.aem-backup-*")))
        self.assertEqual(list(self.destination.rglob("SKILL.md")), [self.destination / "report/SKILL.md"])
        self.checkouts.rename(self.root / "offline-checkouts")
        self.assertEqual(fingerprint(self.destination / "report"), expected)

    def test_failed_replacement_restores_previous_copy(self):
        target = self.installed_copy()
        before = fingerprint(target)
        self.publish_skill_change()
        self.run_cli("update")
        original = os.replace

        def fail_stage(src, dst):
            if Path(src).name.startswith(".aem-stage-"):
                raise OSError("injected failure")
            return original(src, dst)

        with patch("agent_env_man.manager.os.replace", side_effect=fail_stage):
            self.run_cli("apply", code=1)
        self.assertEqual(fingerprint(target), before)
        self.assertIsNone(State(Config(self.config).state_dir).data["pending"])

    def interrupted_replacement(self):
        target = self.installed_copy()
        state = State(Config(self.config).state_dir)
        backup, stage = target.with_name("backup"), target.with_name("stage")
        stage.mkdir()
        (stage / "SKILL.md").write_text("replacement", encoding="utf-8")
        state.data["pending"] = {"key": "report", "target": str(target), "stage": str(stage),
                                 "backup": str(backup), "before": observation(target), "after": observation(stage)}
        state.save()
        os.replace(target, backup)
        os.replace(stage, target)
        return target, backup

    def test_recovery_restores_interrupted_replacement(self):
        target, backup = self.interrupted_replacement()
        expected = fingerprint(backup)
        self.run_cli("apply", code=1)
        self.run_cli("recover")
        self.assertEqual(fingerprint(target), expected)
        self.assertIsNone(State(Config(self.config).state_dir).data["pending"])

    def test_recovery_preserves_concurrent_user_edits(self):
        target, backup = self.interrupted_replacement()
        expected = fingerprint(backup)
        (target / "mine.txt").write_text("user edit", encoding="utf-8")
        self.run_cli("recover", code=1)
        self.assertEqual((target / "mine.txt").read_text(), "user edit")
        self.assertEqual(fingerprint(backup), expected)

    def test_lock_contention_prevents_installation(self):
        self.copy_mode()
        self.bootstrap()
        with lock(Config(self.config).state_dir, holder="aem update"):
            error = self.run_cli("apply", code=1)
        self.assertFalse(self.destination.exists())
        self.assertIn(f"holds the AEM configuration lock: pid {os.getpid()} `aem update`, held for", error)

    def test_git_dirty_divergent_and_detached_checkouts(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        checkout = self.checkouts / ".aem-repositories/report"
        for name in ("unfinished.txt",):
            with self.subTest(name=name):
                (checkout / name).write_text("preserve", encoding="utf-8")
                self.run_cli("update", code=1)
                self.run_cli("apply", code=1)
                self.assertEqual((checkout / name).read_text(), "preserve")
                (checkout / name).unlink()
        (checkout / "local.txt").write_text("local", encoding="utf-8")
        self.commit(checkout)
        head = self.git(checkout, "rev-parse", "HEAD")
        self.run_cli("update", code=1)
        self.publish_skill_change()
        self.run_cli("update", code=1)
        self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), head)
        self.git(checkout, "checkout", "--detach")
        report = self.run_cli("status")
        self.assertIn("expected attached branch", report["sources"][0]["error"])
        self.assertEqual(report["items"][0]["status"], "current")

    def test_ignored_python_cache_allows_link_apply_update_bootstrap_and_detach(self):
        self.require_links()
        (self.repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        self.commit(self.repo)
        self.bootstrap()
        self.run_cli("apply")
        target = self.destination / "report"
        cache = Path(py_compile.compile(str(target / "helper.py"), doraise=True))
        contents = cache.read_bytes()
        self.assertEqual(self.run_cli("status")["sources"][0]["checkout"], "clean")
        self.run_cli("apply")
        self.bootstrap()
        self.publish_skill_change()
        self.run_cli("update")
        self.assertEqual(cache.read_bytes(), contents)
        self.assertIn("Published change", (target / "SKILL.md").read_text())
        self.run_cli("detach", "report")
        self.checkouts.rename(self.root / "offline-checkouts")
        self.assertEqual(cache.read_bytes(), contents)
        self.assertFalse(target.is_symlink())

    def test_ignored_cache_is_preserved_in_copies_and_local_copy_edits_remain_protected(self):
        self.copy_mode()
        (self.repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        self.commit(self.repo)
        self.bootstrap()
        payload = self.checkouts / ".aem-repositories/report/skills/report"
        cache = Path(py_compile.compile(str(payload / "helper.py"), doraise=True))
        self.run_cli("apply")
        copied_cache = self.destination / "report" / cache.relative_to(payload)
        self.assertEqual(copied_cache.read_bytes(), cache.read_bytes())
        self.publish_skill_change()
        self.run_cli("sync")
        self.assertEqual(copied_cache.read_bytes(), cache.read_bytes())
        copied_cache.write_bytes(b"local cache change")
        self.run_cli("apply", code=1)
        self.assertEqual(copied_cache.read_bytes(), b"local cache change")
        self.run_cli("detach", "report")
        self.assertEqual(copied_cache.read_bytes(), b"local cache change")

    def test_incoming_tracked_paths_cannot_overwrite_ignored_files_or_directories(self):
        self.copy_mode()
        (self.repo / ".gitignore").write_text("cache*/\n*.pyc\n", encoding="utf-8")
        self.commit(self.repo)
        self.bootstrap()
        checkout = self.checkouts / ".aem-repositories/report"
        head = self.git(checkout, "rev-parse", "HEAD")
        # Exercise each collision independently so one blocked path cannot mask
        # another. HEAD and the index must stay unchanged on every failure.
        paths = ("skills/report/exact.pyc", "skills/report/parent.pyc", "skills/report/cache dir/data")
        upstream = ("skills/report/exact.pyc", "skills/report/parent.pyc/child", "skills/report/cache dir")
        for name in upstream:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("upstream content", encoding="utf-8")
            self.git(self.repo, "add", "--force", "--", name)
        self.commit(self.repo)
        for name in paths:
            with self.subTest(name=name):
                path = checkout / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("local cache", encoding="utf-8")
                result = self.run_cli("update", code=1)
                self.assertEqual(result[0]["status"], "failed")
                self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), head)
                self.assertEqual(self.git(checkout, "diff", "--cached"), "")
                self.assertEqual(path.read_text(), "local cache")
                path.unlink()
                if name.endswith("/data"):
                    path.parent.rmdir()
        self.run_cli("update")
        for name in upstream:
            self.assertEqual((checkout / name).read_text(), "upstream content")

    def test_ignored_special_payloads_are_still_rejected(self):
        self.require_links()
        self.copy_mode()
        (self.repo / ".gitignore").write_text("cache-link\n", encoding="utf-8")
        self.commit(self.repo)
        self.bootstrap()
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (self.checkouts / ".aem-repositories/report/skills/report/cache-link").symlink_to(outside)
        self.run_cli("apply", code=1)
        self.assertFalse((self.destination / "report").exists())
        self.assertEqual(outside.read_text(), "outside")

    def test_status_refresh_keeps_checkout_and_installation(self):
        target = self.installed_copy()
        checkout = self.checkouts / ".aem-repositories/report"
        before, head = fingerprint(target), self.git(checkout, "rev-parse", "HEAD")
        self.publish_skill_change()
        report = self.run_cli("status", "--refresh")
        self.assertEqual(report["sources"][0]["remote_relation"], "behind")
        self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(fingerprint(target), before)

    def test_timeout_terminates_stalled_subprocess(self):
        real_popen = subprocess.Popen
        processes = []

        def stalled(command, **kwargs):
            if command[0] != "git":
                return real_popen(command, **kwargs)
            process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            processes.append(process)
            return process

        start = time.monotonic()
        with patch("agent_env_man.git_source.subprocess.Popen", side_effect=stalled):
            with self.assertRaisesRegex(Error, "timed out"):
                Git(timeout=0.1).run(None, "--version")
        self.assertLess(time.monotonic() - start, 6)
        self.assertIsNotNone(processes[0].poll())
