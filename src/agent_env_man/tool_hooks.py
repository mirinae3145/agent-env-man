"""Check that hooks other tools install for themselves are present in Claude Code profiles.

A tool hook belongs to the tool, not to AEM: AEM never installs, edits or removes
it. A machine declares what to expect, and the check speaks up only when the
tool is installed and a profile lacks the hook.
"""

from pathlib import Path
import shutil

from .agents import bindings, product_name
from .model import Error, identifier
from .profile_compare import CLAUDE, Profile, _hook_events, _read_json

FIELDS = {'command', 'event', 'contains', 'agents'}


def validate(document):
    """Return the declared tool hooks as {name: {command, event, contains, agents or None}}."""
    declared = document.get('tool_hooks', {})
    if not isinstance(declared, dict):
        raise Error('tool_hooks must be a TOML table')
    registered = bindings(document)
    result = {}
    for name, value in declared.items():
        identifier(name)
        if not isinstance(value, dict) or set(value) - FIELDS or not {'command', 'event', 'contains'} <= set(value):
            raise Error(f'tool_hooks.{name} requires command, event and contains; agents is optional')
        for field in ('command', 'event', 'contains'):
            if not isinstance(value[field], str) or not value[field]:
                raise Error(f'tool_hooks.{name}.{field} must be a nonempty string')
        if value['event'] not in CLAUDE.command_events:
            raise Error(f"tool_hooks.{name}.event must be one of {', '.join(CLAUDE.command_events)}")
        agents = value.get('agents')
        if agents is not None:
            # An empty list would read as "check none" but would check every profile, so it is refused.
            if not isinstance(agents, list) or not agents or not all(isinstance(agent, str) for agent in agents):
                raise Error(f'tool_hooks.{name}.agents must be a nonempty list of agent names')
            for agent in agents:
                if agent not in registered or product_name(agent) != CLAUDE.name:
                    raise Error(f'tool_hooks.{name}.agents: {agent} is not a registered Claude Code agent')
        result[name] = {key: value[key] for key in ('command', 'event', 'contains')} | {
            'agents': list(agents) if agents is not None else None}
    return result


def _present(profile, event, contains):
    path = profile.root / CLAUDE.hook_name
    groups = _hook_events(_read_json(path) or {}, path).get(event, [])
    return any(contains in hook.get('command', '') for group in groups
               for hook in group.get('hooks', []) if isinstance(hook, dict))


def check(document, *, selected=(), which=shutil.which):
    """Report each declared tool: absent (skipped), or present/missing per Claude Code profile."""
    declared = validate(document)
    registered = {name: binding for name, binding in bindings(document).items() if product_name(name) == CLAUDE.name}
    unknown = [name for name in selected if name not in registered]
    if unknown:
        raise Error('Not a registered Claude Code agent: ' + ', '.join(unknown))
    tools = []
    for name, tool in declared.items():
        path = which(tool['command'])
        entry = {'tool': name, 'command': tool['command'], 'installed': path is not None, 'agents': []}
        for agent in tool['agents'] or registered:
            if selected and agent not in selected:
                continue
            if path is None:
                break
            root = registered[agent]['root']
            profile = Profile(agent, Path(root), Path(registered[agent]['skills']))
            present = _present(profile, tool['event'], tool['contains'])
            item = {'agent': agent, 'root': root, 'status': 'present' if present else 'missing'}
            if not present:
                item['advice'] = (f"{tool['command']} is installed but {tool['event']} has no hook containing "
                                  f"'{tool['contains']}' in {agent}. Install the tool's Claude Code integration "
                                  f"for this profile (run it with CLAUDE_CONFIG_DIR={root}) or repair it; "
                                  "AEM does not install tool hooks.")
            entry['agents'].append(item)
        tools.append(entry)
    missing = sum(1 for tool in tools for item in tool['agents'] if item['status'] == 'missing')
    return {'tools': tools, 'missing': missing}


def render(report):
    if not report['tools']:
        return 'No tool hooks are declared.'
    lines = []
    for tool in report['tools']:
        if not tool['installed']:
            lines.append(f"{tool['tool']}: {tool['command']} not installed, skipped")
            continue
        lines.append(f"{tool['tool']}: " + ', '.join(f"{item['agent']} {item['status']}" for item in tool['agents']))
        lines += [f"  {item['advice']}" for item in tool['agents'] if item['status'] == 'missing']
    return '\n'.join(lines)
