"""Source-independent update policies and event-driven execution.

Callers supply events; this module neither installs hooks nor owns a scheduler.
Policy resolution accepts mappings so it is independent of catalog transport.
"""

import math
import time
from pathlib import Path

from .git_source import Git, now
from .model import Error, identifier


TRIGGERS = ("shell-start", "agent-start", "interval")
DEFAULTS = {"trigger": "manual", "action": "sync", "min_interval": 600, "timeout": 30}


def policy_fields(value, location, *, allow_policy=False):
    """Validate explicit fields before merging, including unused named policies."""
    allowed = set(DEFAULTS) | ({"policy"} if allow_policy else set())
    if not isinstance(value, dict) or set(value) - allowed:
        raise Error(f"{location}: expected update fields {', '.join(sorted(allowed))}")
    result = dict(value)
    if "policy" in result:
        identifier(result["policy"])
    if "trigger" in result:
        triggers = result["trigger"]
        if isinstance(triggers, str):
            triggers = [triggers]
        if (not isinstance(triggers, list) or not triggers
                or any(not isinstance(t, str) or t not in (*TRIGGERS, "manual") for t in triggers)
                or len(set(triggers)) != len(triggers)
                or ("manual" in triggers and len(triggers) != 1)):
            raise Error(f"{location}: trigger must be manual or one or more unique events: {', '.join(TRIGGERS)}")
        result["trigger"] = list(triggers)
    if "action" in result and result["action"] not in ("check", "sync"):
        raise Error(f"{location}: action must be check or sync")
    for key in ("min_interval", "timeout"):
        if key in result:
            number = result[key]
            if (isinstance(number, bool) or not isinstance(number, (int, float))
                    or not math.isfinite(number) or number < 0 or (key == "timeout" and number == 0)):
                raise Error(f"{location}: {key} must be finite and {'positive' if key == 'timeout' else 'nonnegative'}")
    return result


def set_catalog_policy(document, args):
    """Apply only supplied device-policy fields; trigger lists replace saved lists."""
    values = {field: getattr(args, option) for field, option in
              (('trigger', 'catalog_trigger'), ('min_interval', 'catalog_interval'), ('timeout', 'catalog_timeout'))
              if getattr(args, option) is not None}
    if values:
        policy = document.setdefault('catalog_update', {})
        policy.update(values)
        catalog_policy(policy)
    return bool(values)


def catalog_policy(value):
    """Resolve a machine-local catalog update policy without loading its catalog."""
    if not isinstance(value, dict) or set(value) - {'trigger', 'min_interval', 'timeout'}:
        raise Error('catalog_update accepts only trigger, min_interval, and timeout')
    return {**policy_fields({'trigger': 'manual', 'min_interval': 3600, 'timeout': 5}, 'catalog_update defaults'),
            **policy_fields(value, 'catalog_update')}


def resolve_policies(updates, skills, *, default_trigger=None, kind="skills"):
    """Merge built-ins, global defaults, one named policy, then item fields.

    Trigger lists replace rather than append; manual explicitly disables events.
    Source-specific capabilities are checked here, before any network operation.
    """
    if not isinstance(updates, dict) or set(updates) - {"defaults", "policies"}:
        raise Error("updates must contain only defaults and policies tables")
    builtins = dict(DEFAULTS)
    if default_trigger is not None:
        builtins["trigger"] = default_trigger
    defaults = policy_fields(builtins, "built-in defaults")
    defaults.update(policy_fields(updates.get("defaults", {}), "updates.defaults"))
    named = updates.get("policies", {})
    if not isinstance(named, dict):
        raise Error("updates.policies must be a table")
    policies = {identifier(name): policy_fields(value, f"updates.policies.{name}")
                for name, value in named.items()}
    result = {}
    for name, skill in skills.items():
        own = policy_fields(skill.get("update", {}), f"{kind}.{name}.update", allow_policy=True)
        selection = own.pop("policy", None)
        if selection is not None and selection not in policies:
            label = "Directory" if kind == "directories" else "Skill"
            raise Error(f"{label} {name}: unknown update policy {selection!r}")
        effective = {**defaults, **policies.get(selection, {}), **own}
        if kind == "skills" and skill.get("type", "git" if "repo" in skill else None) != "git":
            raise Error(f"Skill {name}: update actions are unsupported for source type {skill.get('type')!r}")
        result[name] = effective
    return result


def run_updates(manager, trigger, names=(), *, dry_run=False):
    """Run due skills and directories independently under the configuration lock.

    Persist attempts before network access, so failures and interruptions are
    throttled too. Events share one per-skill clock; manual commands do not use it.
    No replacements, adoption, or reattachment are authorized by automation.
    """
    if trigger not in TRIGGERS:
        raise Error(f"Unknown automatic update trigger: {trigger}")
    if manager.config.automation['mode'] == 'off':
        return [], False
    if manager.config.automation['mode'] == 'full':
        raise Error('Use automation --trigger EVENT in full mode')
    policies = manager.config.update_policies()
    if set(names) - policies.keys():
        raise Error("Unknown catalog skill or directory selection")
    manager.state.ready()
    sources = manager.config.sources
    report, failed = [], False
    initial_revisions = {}
    fetch_cache = {}
    for name, policy in policies.items():
        if names and name not in names:
            continue
        entry = {"directory" if name in manager.config._directories else "skill": name, "policy": policy}
        report.append(entry)
        previous = manager.state.data["sources"].get(name, {}).get("automation", {})
        current = time.time()
        if trigger not in policy["trigger"]:
            entry["status"] = "not-triggered"
        elif all(manager.state.data["items"].get(item.key, {}).get("detached")
                 for item in manager.config.declarations(sources[name])):
            entry["status"] = "detached"
        elif "last_attempt" in previous and current - previous["last_attempt"] < policy["min_interval"]:
            entry["status"] = "throttled"
        else:
            entry["status"] = "planned"
        if entry["status"] != "planned" or dry_run:
            continue
        # A failed earlier transaction can leave a recovery journal. Do not
        # start another skill until that journal has been resolved.
        manager.state.ready()
        source_state = manager.state.data["sources"].setdefault(name, {})
        attempt = {"last_attempt": current, "trigger": trigger, "action": policy["action"], "status": "running"}
        source_state["automation"] = attempt
        manager.state.save()
        try:
            source = manager.delivery_source(sources[name])
            if not source.git:
                if not source.path.is_dir():
                    raise Error(f"External source missing: {source.path}")
                for item in manager.config.declarations(sources[name]):
                    manager.payload(item)
                entry["status"] = "external-no-fetch"
                if policy["action"] == "sync":
                    entry["apply"] = manager.apply([name], timeout=policy["timeout"])
                    entry["status"] = "synced"
            elif policy["action"] == "check":
                git = Git(policy["timeout"], fetch_cache=fetch_cache)
                revision = git.fetch(source)
                source_state.update(last_fetch=now(), observed_revision=revision)
                entry.update(status="checked", remote_relation=git.relation(source, revision=revision))
            else:
                # Keep the first observed HEAD for shared checkouts: an earlier
                # skill in this invocation may already have advanced the branch.
                git = Git(policy["timeout"], fetch_cache=fetch_cache)
                if source.path not in initial_revisions:
                    initial_revisions[source.path] = git.run(source.path, "rev-parse", "HEAD").stdout
                entry["previous_revision"] = initial_revisions[source.path]
                outcomes, update_failed = manager.update([name], timeout=policy["timeout"], fetch_cache=fetch_cache)
                if update_failed:
                    raise Error(outcomes[0]["error"])
                entry["revision"] = git.run(source.path, "rev-parse", "HEAD").stdout
                entry["apply"] = manager.apply([name], timeout=policy["timeout"])
                entry["status"] = "synced"
            attempt.update(status=entry["status"], last_success=time.time())
        except (Error, OSError, ValueError) as exc:
            failed = True
            entry.update(status="failed", error=str(exc))
            attempt.update(status="failed", error=str(exc))
        manager.state.save()
    return report, failed


def run_settings_updates(manager, trigger, *, dry_run=False):
    """Receive and apply due prepared settings without collecting or publishing.

    Settings schedules are independent of skill defaults and clocks. Persist
    attempts before delivery and stop application on a shared merge conflict.
    The ordinary apply merge preserves actual-file edits and unmanaged fields.
    """
    if trigger not in TRIGGERS:
        raise Error(f"Unknown automatic update trigger: {trigger}")
    if manager.config.automation['mode'] == 'off':
        return [], False
    if manager.config.automation['mode'] == 'full':
        raise Error('Use automation --trigger EVENT in full mode')
    policies = manager.config.settings_update_policies()
    manager.state.ready()
    report, failed = [], False
    initial_revisions = {}
    for name, policy in policies.items():
        entry = {"setting": name, "policy": policy}
        report.append(entry)
        record = manager.state.data['items'].get(f'{name}:settings')
        previous = manager.state.data['sources'].get(name, {}).get('settings_automation', {})
        current = time.time()
        if trigger not in policy['trigger']:
            entry['status'] = 'not-triggered'
        elif record and record.get('detached'):
            entry['status'] = 'detached'
        elif not record:
            entry['status'] = 'not-prepared'
        elif current - previous.get('last_attempt', float('-inf')) < policy['min_interval']:
            entry['status'] = 'throttled'
        else:
            entry['status'] = 'planned'
        if entry['status'] != 'planned' or dry_run:
            continue
        manager.state.ready()
        attempt = {'last_attempt': current, 'trigger': trigger, 'action': 'sync', 'status': 'running'}
        manager.state.data['sources'].setdefault(name, {})['settings_automation'] = attempt
        manager.state.save()
        try:
            source = manager.delivery_source(manager.config.sources[name])
            if source.git:
                git = Git(policy['timeout'])
                if source.path not in initial_revisions:
                    initial_revisions[source.path] = git.run(source.path, 'rev-parse', 'HEAD').stdout
                entry['previous_revision'] = initial_revisions[source.path]
            entry['update'], update_failed = manager.update([name], timeout=policy['timeout'])
            if source.git:
                entry['revision'] = git.run(source.path, 'rev-parse', 'HEAD').stdout
            if update_failed:
                raise Error(f'Setting {name}: reception failed; application skipped')
            entry['apply'] = manager.apply([name], timeout=policy['timeout'])
            entry['status'] = 'synced'
            attempt.update(status='synced', last_success=time.time())
        except (Error, OSError, ValueError) as exc:
            failed = True
            entry.update(status='failed', error=str(exc))
            attempt.update(status='failed', error=str(exc))
        manager.state.save()
    return report, failed


def startup_skills_changed(outcomes, records, agent, sources):
    """Include live links changed indirectly by an advanced shared checkout."""
    applied = set()
    advanced_checkouts = set()
    for outcome in outcomes:
        advanced = (outcome.get("previous_revision") is not None
                    and outcome.get("revision") is not None
                    and outcome["previous_revision"] != outcome["revision"])
        if advanced:
            source = sources.get(outcome.get("skill", outcome.get("directory", outcome.get("setting"))))
            if source is not None:
                advanced_checkouts.add(source.path)
        if outcome.get("status") == "synced":
            applied.update(item["item"] for item in outcome.get("apply", [])
                           if advanced or item["action"] == "install")
    for key, record in records.items():
        if (record.get("kind") != "skill" or record.get("detached")
                or agent not in record.get("agents", [record.get("agent", "codex")])):
            continue
        if key in applied:
            return True
        if record.get("mode") == "link" and any(
                Path(record["source"]).is_relative_to(checkout)
                for checkout in advanced_checkouts):
            return True
    return False


def startup_briefing(outcomes):
    """Summarize completed changes, not successful but unchanged sync attempts.

    Use manager-owned metadata only, keeping repository text out of hook context.
    A bounded list fits the existing startup hook's context allowance.
    """
    changes = []
    for outcome in outcomes:
        if outcome.get("status") != "synced":
            continue
        before, after = outcome.get("previous_revision"), outcome.get("revision")
        if before and after and before != after:
            detail = f"{before[:8]} -> {after[:8]}"
        elif any(item["action"] == "install" for item in outcome.get("apply", [])):
            detail = "installed/refreshed"
        else:
            continue
        changes.append(f"{outcome.get('skill', outcome.get('directory'))}: {detail}")
    if not changes:
        return ""
    label = "content" if any("directory" in outcome for outcome in outcomes) else "skill"
    summary = f"AEM {label} updates: " + "; ".join(changes[:10])
    if len(changes) > 10:
        summary += f"; +{len(changes) - 10} more (see aem status)"
    return summary
