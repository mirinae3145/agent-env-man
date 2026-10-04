"""Offline Codex hook installation preserves other hooks and never grants trust."""

import base64
from copy import deepcopy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from agent_env_man import hooks
from agent_env_man.agents import profile
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, lock
from test_instructions import InstructionFixture


class HookInstallation(InstructionFixture):
    def hook_file(self):
        return self.agent / "hooks.json"

    def write_hooks(self, document):
        self.agent.mkdir(exist_ok=True)
        self.hook_file().write_text(json.dumps(document), encoding="utf-8")

    def existing_hooks(self):
        return {"description": "User configuration", "custom": {"keep": True}, "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo existing"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}

    def test_bootstrap_and_preview_do_not_register_and_apply_reports_trust(self):
        self.configure()
        self.assertFalse(self.hook_file().exists())
        preview = self.run_cli("apply", "--item", "personal:entry", "--dry-run")
        self.assertEqual([r["item"] for r in preview], ["personal:bundle", "personal:entry", "personal:hook"])
        self.assertEqual(preview[-1]["hook"], "would-register")
        self.assertIn("/hooks", preview[-1]["notice"])
        self.assertFalse(self.hook_file().exists())
        self.assertFalse((self.agent / "AGENTS.md").exists())
        result = self.run_cli("apply", "--item", "personal:entry")
        self.assertEqual(result[-1]["hook"], "registered")
        self.assertEqual(result[-1]["trust"], "not-managed-by-aem")
        self.assertFalse((self.agent / "config.toml").exists())
        self.assertEqual((self.agent / "AGENTS.md").read_bytes(), (self.bundle / "start.md").read_bytes())

    def test_unrelated_hooks_and_metadata_survive_and_reapply_is_idempotent(self):
        self.configure()
        initial = self.existing_hooks()
        self.write_hooks(initial)
        self.run_cli("apply")
        after = json.loads(self.hook_file().read_text())
        self.assertEqual(after["description"], initial["description"])
        self.assertEqual(after["custom"], initial["custom"])
        self.assertEqual(after["hooks"]["Stop"], initial["hooks"]["Stop"])
        self.assertEqual(after["hooks"]["SessionStart"][:-1], initial["hooks"]["SessionStart"])
        before = self.hook_file().read_bytes()
        result = self.run_cli("apply")
        self.assertEqual(result[-1]["hook"], "unchanged")
        self.assertEqual(before, self.hook_file().read_bytes())
        # Changes outside the owned group must not be reported as local conflicts.
        after["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo changed by user"
        self.write_hooks(after)
        statuses = {i["item"]: i for i in self.run_cli("status")["items"]}
        self.assertEqual(statuses["personal:hook"]["status"], "current")
        self.run_cli("apply")
        self.assertEqual(json.loads(self.hook_file().read_text()), after)

    def test_modified_owned_hook_is_preserved_until_explicit_replace(self):
        self.configure()
        self.write_hooks(self.existing_hooks())
        self.run_cli("apply")
        changed = json.loads(self.hook_file().read_text())
        changed["hooks"]["SessionStart"][-1]["hooks"][0]["command"] = "echo local override"
        self.write_hooks(changed)
        self.run_cli("apply", code=1)
        self.assertEqual(json.loads(self.hook_file().read_text()), changed)
        self.run_cli("apply", "--item", "personal:entry", "--replace")
        restored = json.loads(self.hook_file().read_text())
        self.assertEqual(restored["hooks"]["SessionStart"][0], changed["hooks"]["SessionStart"][0])
        self.assertNotEqual(restored["hooks"]["SessionStart"][-1], changed["hooks"]["SessionStart"][-1])

    def test_invalid_hook_file_prevents_any_installation(self):
        self.configure()
        self.agent.mkdir()
        for content in ('{broken', '{"hooks": []}', '{"hooks":{},"hooks":{}}', '{"hooks":{"SessionStart":{}}}'):
            with self.subTest(content=content):
                self.hook_file().write_text(content)
                self.run_cli("apply", code=1)
                self.assertEqual(self.hook_file().read_text(), content)
                self.assertFalse((self.rules / "personal").exists())
                self.assertFalse((self.agent / "AGENTS.md").exists())

    def test_hook_file_symlink_is_not_followed_or_replaced(self):
        self.configure()
        self.agent.mkdir()
        other = self.root / "other-hooks.json"
        other.write_text('{}')
        self.hook_file().symlink_to(other)
        self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertTrue(self.hook_file().is_symlink())
        self.assertEqual(other.read_text(), '{}')

    def test_hook_callback_is_metadata_only_and_survives_detach(self):
        self.configure()
        self.run_cli("apply")
        state_path = Config(self.config).state_dir / "state.json"
        before = state_path.read_bytes()
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "SessionStart")
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(json.loads(context.split("\n")[1])["root"], str(self.bundle))
        self.assertNotIn("Read development/rules.md", context)
        self.assertEqual(state_path.read_bytes(), before)
        registered = self.hook_file().read_bytes()
        self.catalog.unlink()
        self.run_cli("detach", "personal:bundle", "personal:entry")
        shutil.rmtree(self.external)
        self.assertEqual(self.hook_file().read_bytes(), registered)
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertEqual(json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[1])["root"], str(self.rules / "personal"))
        self.assertFalse((self.agent / "AGENTS.md").is_symlink())
        self.assertTrue(State(Config(self.config).state_dir).data["items"]["personal:hook"]["detached"])

    def test_missing_source_or_pending_recovery_produces_structured_stop(self):
        self.configure()
        self.run_cli("apply")
        shutil.rmtree(self.external)
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertIs(result["continue"], False)
        self.assertIn("lookup failed", result["systemMessage"])
        state = State(Config(self.config).state_dir)
        state.data["pending"] = {"example": "pending transaction"}
        state.save()
        result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertIs(result["continue"], False)
        self.assertIn("recover", result["stopReason"])

    def test_instruction_callbacks_retry_contention_and_read_state_after_acquiring(self):
        self.configure()
        self.run_cli("apply")
        directory = Config(self.config).state_dir
        for command in (("agent-hook", "--agent", "codex"),):
            for pending in (False, True):
                with self.subTest(command=command, pending=pending), ExitStack() as holder:
                    state = State(directory)
                    state.data["pending"] = None
                    state.save()
                    holder.enter_context(lock(directory))

                    def finish_writer(_delay):
                        if pending:
                            state.data["pending"] = {"example": "interrupted transaction"}
                            state.save()
                        holder.close()

                    with patch("agent_env_man.process_lock.time.sleep", side_effect=finish_writer) as retry:
                        result = self.run_cli(*command, "personal")
                    retry.assert_called_once()
                    if pending:
                        self.assertIs(result["continue"], False)
                        self.assertIn("recover", result["stopReason"])
                    else:
                        self.assertEqual(json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[1])["root"], str(self.bundle))

    def test_instruction_callback_waits_for_installation_lock(self):
        self.configure()
        self.run_cli("apply")
        directory = self.config.parent / "installation-lock"
        with ExitStack() as holder:
            holder.enter_context(lock(directory))
            with patch("agent_env_man.cli_runtime.self_update.installation_lock", return_value=directory), \
                    patch("agent_env_man.process_lock.time.sleep", side_effect=lambda _: holder.close()) as retry:
                result = self.run_cli("agent-hook", "personal", "--agent", "codex")
            retry.assert_called_once()
        self.assertEqual(json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[1])["root"], str(self.bundle))

    def test_instruction_callback_shares_wait_budget_across_locks(self):
        self.configure()
        self.run_cli("apply")
        directory = self.config.parent / "installation-lock"
        # Model four seconds spent acquiring the installation lock.
        with patch("agent_env_man.cli_runtime.self_update.installation_lock", return_value=directory), \
                patch("agent_env_man.cli_runtime.time.monotonic", side_effect=[0, 0, 4]), \
                patch("agent_env_man.cli_runtime.lock", return_value=ExitStack()) as acquire:
            result = self.run_cli("agent-hook", "personal", "--agent", "codex")
        self.assertEqual([call.kwargs["timeout"] for call in acquire.call_args_list], [5, 1])
        self.assertEqual(json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n")[1])["root"], str(self.bundle))

    def test_instruction_callbacks_read_stable_metadata_when_contention_outlasts_wait_budget(self):
        self.configure()
        self.run_cli("apply")
        directory = Config(self.config).state_dir
        before = (directory / "state.json").read_bytes()
        for command in (("agent-hook", "--agent", "codex"),):
            with self.subTest(command=command), lock(directory):
                with patch("agent_env_man.process_lock.time.monotonic", side_effect=[0, 0, 0, 0, 5]), \
                        patch("agent_env_man.process_lock.time.sleep") as retry:
                    result = self.run_cli(*command, "personal")
                retry.assert_called_once()
                self.assertIn("hookSpecificOutput", result)
        self.assertEqual((directory / "state.json").read_bytes(), before)

    def test_contended_snapshot_refuses_pending_recovery_and_changed_state(self):
        self.configure()
        self.run_cli("apply")
        directory = Config(self.config).state_dir
        state = State(directory)
        for pending in (True, False):
            state.data['pending'] = {'example': 'pending'} if pending else None
            state.save()
            original = Manager.hook_context

            def changing_lookup(manager, *args):
                result = original(manager, *args)
                state.data['snapshot_changed'] = True
                state.save()
                return result

            with lock(directory), patch('agent_env_man.cli_runtime.lock', side_effect=Error('contended')), \
                    patch.object(Manager, 'hook_context', changing_lookup):
                result = self.run_cli('agent-hook', 'personal', '--agent', 'codex')
            self.assertIs(result['continue'], False)
            self.assertIn('recover' if pending else 'changed during lookup', result['stopReason'])

    def test_contended_snapshot_refuses_changed_machine_file_and_replaced_links(self):
        self.configure()
        self.run_cli('apply')
        original = Manager.hook_context

        def changing_lookup(manager, *args):
            result = original(manager, *args)
            self.config.write_text(self.config.read_text() + '\n# concurrent setup edit\n')
            return result

        with patch('agent_env_man.cli_runtime.lock', side_effect=Error('contended')), \
                patch.object(Manager, 'hook_context', changing_lookup):
            result = self.run_cli('agent-hook', 'personal', '--agent', 'codex')
        self.assertIs(result['continue'], False)
        self.assertIn('changed during lookup', result['stopReason'])
        target = self.agent / 'AGENTS.md'
        target.unlink()
        target.write_text('# Unmanaged replacement\n')
        with patch('agent_env_man.cli_runtime.lock', side_effect=Error('contended')):
            result = self.run_cli('agent-hook', 'personal', '--agent', 'codex')
        self.assertIs(result['continue'], False)
        self.assertIn('replaced', result['stopReason'])

    def test_startup_waits_for_short_instruction_lock_contention(self):
        self.configure()
        self.run_cli('apply')
        with ExitStack() as holder:
            holder.enter_context(lock(Config(self.config).state_dir))
            with patch('agent_env_man.process_lock.time.sleep', side_effect=lambda _: holder.close()) as retry:
                self.run_cli('startup', '--trigger', 'agent-start', '--agent', 'codex')
            retry.assert_called_once()
        self.assertIn('startup', State(Config(self.config).state_dir).data)

    def test_hook_transaction_failure_restores_existing_hooks_and_can_retry(self):
        self.configure()
        initial = self.existing_hooks()
        self.write_hooks(initial)
        original = os.replace

        def fail_hook(src, dst):
            if Path(src).name.startswith(".aem-stage-") and Path(dst) == self.hook_file():
                raise OSError("Injected hook installation failure")
            return original(src, dst)

        with patch("agent_env_man.manager.os.replace", side_effect=fail_hook):
            self.run_cli("apply", code=1)
        self.assertEqual(json.loads(self.hook_file().read_text()), initial)
        state = State(Config(self.config).state_dir)
        self.assertIsNone(state.data["pending"])
        self.assertNotIn("personal:hook", state.data["items"])
        self.assertTrue((self.agent / "AGENTS.md").is_symlink())
        self.run_cli("apply")
        self.assertEqual(len(json.loads(self.hook_file().read_text())["hooks"]["SessionStart"]), 2)

    def test_duplicate_marker_is_never_silently_removed(self):
        self.configure()
        self.run_cli("apply")
        doc = json.loads(self.hook_file().read_text())
        doc["hooks"]["SessionStart"].append(doc["hooks"]["SessionStart"][0])
        self.write_hooks(doc)
        self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertEqual(json.loads(self.hook_file().read_text()), doc)

    def test_implicit_bundle_does_not_gain_replace_permission(self):
        self.configure()
        target = self.rules / "personal"
        target.mkdir(parents=True)
        (target / "local.txt").write_text("Keep")
        self.run_cli("apply", "--item", "personal:entry", "--replace", code=1)
        self.assertEqual((target / "local.txt").read_text(), "Keep")

    def test_other_bundle_shares_one_hook_file_transaction(self):
        self.configure()
        import tomlkit

        doc = tomlkit.parse(self.catalog.read_text())
        doc["instructions"]["other"] = deepcopy(doc["instructions"]["personal"])
        doc['instructions']['other']['install']['bundle']['destination'] = "other"
        doc['instructions']['other']['install']['entry']['destination'] = "OTHER.md"
        self.catalog.write_text(tomlkit.dumps(doc))
        original = os.replace
        def fail_hook(src, dst):
            if Path(src).name.startswith(".aem-stage-") and Path(dst) == self.hook_file():
                raise OSError("Grouped hook failure")
            return original(src, dst)
        with patch("agent_env_man.manager.os.replace", side_effect=fail_hook):
            self.run_cli("apply", code=1)
        state = State(Config(self.config).state_dir).data
        self.assertIsNone(state["pending"])
        self.assertNotIn("personal:hook", state["items"])
        self.assertNotIn("other:hook", state["items"])
        self.assertFalse(self.hook_file().exists())
        self.run_cli("apply")
        before = self.hook_file().read_bytes()
        self.assertEqual(len(json.loads(before)["hooks"]["SessionStart"]), 2)
        self.run_cli("apply")
        self.assertEqual(self.hook_file().read_bytes(), before)

    def test_windows_command_encodes_literal_arguments(self):
        # Verify platform-independent encoding without claiming a Windows run.
        path = Path("C:/Users/space ' and $name/machine.toml")
        with patch.object(hooks.os, "name", "nt"):
            _, group = profile("codex").definition(path, "personal")
        command = group["hooks"][0]["command"]
        self.assertTrue(command.startswith("powershell.exe -NoProfile -NonInteractive -EncodedCommand "))
        decoded = base64.b64decode(command.split()[-1]).decode("utf-16le")
        self.assertIn("'" + str(path).replace("'", "''") + "'", decoded)
        self.assertIn("'agent-hook' 'personal' '--agent' 'codex'", decoded)

    def test_removed_hook_is_not_silently_reinstalled(self):
        self.configure()
        self.run_cli("apply")
        self.write_hooks(self.existing_hooks())
        before = self.hook_file().read_bytes()
        self.run_cli("apply", code=1)
        self.assertEqual(self.hook_file().read_bytes(), before)
        self.run_cli("apply", "--item", "personal:entry", "--replace")
        self.assertEqual(len(json.loads(self.hook_file().read_text())["hooks"]["SessionStart"]), 2)

    def test_hook_preflight_does_not_overwrite_concurrent_edit(self):
        self.configure()
        self.write_hooks(self.existing_hooks())
        config = Config(self.config)
        manager = Manager(config, State(config.state_dir))
        item = next(i for i in manager.items() if i.kind == "instruction-hook")
        plan = manager.plan(item)
        changed = self.existing_hooks()
        changed["description"] = "Edited after preflight"
        self.write_hooks(changed)
        from agent_env_man.model import Error
        with self.assertRaises(Error):
            manager.install(plan)
        self.assertEqual(json.loads(self.hook_file().read_text()), changed)

    def test_reattach_retained_hook_requires_no_duplicate_or_implicit_replacement(self):
        self.configure()
        self.run_cli("apply")
        self.run_cli("detach", "personal:bundle", "personal:entry")
        self.run_cli("apply", "--item", "personal:entry", "--reattach", "--replace", code=1)
        self.run_cli("apply", "--item", "personal:bundle", "--item", "personal:entry", "--reattach", "--replace")
        self.assertEqual(len(json.loads(self.hook_file().read_text())["hooks"]["SessionStart"]), 1)
        self.assertTrue((self.agent / "AGENTS.md").is_symlink())

    def test_active_entry_link_guard_survives_detached_bundle_and_removed_declaration(self):
        self.configure(git=True)
        self.run_cli("apply")
        self.run_cli("detach", "personal:bundle")
        (self.bundle / "start.md").unlink()
        self.commit(self.external)
        import tomlkit
        doc = tomlkit.parse(self.catalog.read_text())
        del doc["instructions"]
        doc["skills"]["other"] = {'subdir': '.', 'source': 'guidance'}
        self.catalog.write_text(tomlkit.dumps(doc))
        self.run_cli("update", "other", code=1)
        self.assertTrue((self.agent / "AGENTS.md").is_file())

    def test_nested_entry_reference_context_across_detach(self):
        import tomlkit

        self.configure()
        (self.bundle / "entry").mkdir()
        entry_text = "Read ../development/rules.md; unique entry payload"
        (self.bundle / "entry/start.md").write_text(entry_text, encoding="utf-8")
        document = tomlkit.parse(self.catalog.read_text())
        document["instructions"]["personal"]["entry"] = "entry/start.md"
        self.catalog.write_text(tomlkit.dumps(document), encoding="utf-8")
        self.run_cli("apply")
        installed_entry = self.agent / "AGENTS.md"
        self.assertTrue(installed_entry.is_symlink())
        self.assertEqual(installed_entry.read_text(), entry_text)

        for stage in ("linked", "bundle-detached", "fully-detached"):
            with self.subTest(stage=stage):
                if stage == "bundle-detached":
                    self.run_cli("detach", "personal:bundle")
                    (self.bundle / "development/rules.md").write_text("Live change", encoding="utf-8")
                elif stage == "fully-detached":
                    self.run_cli("detach", "personal:entry")
                    self.catalog.unlink()
                    shutil.rmtree(self.external)
                state_path = Path(str(self.config) + ".state/state.json")
                before = state_path.read_bytes()
                context = self.run_cli("agent-hook", "personal", "--agent", "codex")["hookSpecificOutput"]["additionalContext"]
                locations = json.loads(context.split("\n")[1])
                root = self.rules / "personal" if stage == "fully-detached" else self.bundle
                self.assertEqual(locations, {"root": str(root), "entry": str(root / "entry/start.md"),
                                             "global_entry": str(installed_entry)})
                referenced = Path(locations["entry"]).parent / "../development/rules.md"
                expected = "Live change" if stage == "bundle-detached" else "User-supplied guidance\n"
                self.assertEqual(referenced.read_text(), expected)
                self.assertNotEqual(Path(locations["entry"]).parent, Path(locations["root"]))
                self.assertIn("If its contents are already present in your context", context)
                self.assertIn("do not reread them solely to establish these paths", context)
                self.assertIn("parent directory of entry", context)
                self.assertIn("each referring document's own directory", context)
                self.assertIn("user documents explicitly specify", context)
                self.assertIn("applicability and reading order", context)
                self.assertNotIn(entry_text, context)
                self.assertEqual(state_path.read_bytes(), before)

    def test_partial_bundle_detach_keeps_hook_aligned_with_live_global_entry(self):
        self.configure()
        self.run_cli("apply")
        self.run_cli("detach", "personal:bundle")
        (self.bundle / "development/rules.md").write_text("Live source change")
        context = self.run_cli("agent-hook", "personal", "--agent", "codex")["hookSpecificOutput"]["additionalContext"]
        metadata = json.loads(context.split("\n")[1])
        self.assertEqual(metadata, {'root': str(self.bundle), 'entry': str(self.bundle / 'start.md'), 'global_entry': str(self.agent / 'AGENTS.md')})
        diagnostic = self.run_cli("locate", "personal")
        self.assertEqual(diagnostic["installed_root"], str(self.rules / "personal"))
        self.assertTrue(diagnostic["detached"])
        self.assertEqual(metadata["root"], str(self.bundle))
        self.assertEqual(Path(metadata["root"], "development/rules.md").read_text(), "Live source change")
        self.run_cli("detach", "personal:entry")
        context = self.run_cli("agent-hook", "personal", "--agent", "codex")["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(json.loads(context.split("\n")[1]), {'root': str(self.rules / 'personal'), 'entry': str(self.rules / 'personal/start.md'), 'global_entry': str(self.agent / 'AGENTS.md')})
