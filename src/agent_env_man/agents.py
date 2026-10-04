"""Built-in agent capabilities injected at the machine boundary.

Profiles own product syntax; the manager owns delivery and installation safety.
The registry is intentionally internal, not a user-loadable plugin mechanism.
"""
from dataclasses import dataclass
import os
import math
from pathlib import Path

from . import hooks
from .model import Error


# Source-level choice for Codex startup briefings, independent of machine setup.
# systemMessage displays a UI warning; additionalContext informs the model.
# Neither mode asks the model to announce the update in its response.
STARTUP_BRIEFING_OUTPUT = "systemMessage"


@dataclass(frozen=True)
class Codex:
    name: str = 'codex'
    entry_name: str = 'AGENTS.md'
    hook_name: str = 'hooks.json'
    shared_settings_format: str | None = None
    command_events: tuple = ('SessionStart', 'SessionEnd', 'PreToolUse', 'PermissionRequest',
                             'PostToolUse', 'PreCompact', 'PostCompact', 'SubagentStart',
                             'SubagentStop', 'UserPromptSubmit', 'Stop', 'Interrupt')
    hook_timeout_limits: tuple = (('SessionEnd', 3), ('Interrupt', 3))
    unmatched_hook_events: tuple = ('UserPromptSubmit', 'Stop', 'Interrupt')

    def personal_command(self, marker, args):
        from .personal_hooks import direct_command
        return direct_command(marker, args)
    notice: str = hooks.TRUST_NOTICE
    failure_to_stderr: bool = False
    failure_exit_code: int = 0

    def defaults(self):
        return {'root': str(Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()),
                'skills': str(Path.home() / '.agents/skills')}

    def definition(self, config, name, *, startup=False, startup_timeout=10):
        timeout = math.ceil(startup_timeout) if startup else 10
        if not 0 < timeout < 2**64:
            raise Error('Codex hook timeout must fit an unsigned 64-bit integer')
        identity = f'{self.name}:startup' if startup else f'{self.name}:{name}'
        args = ['startup', '--trigger', 'agent-start', '--agent', self.name] if startup else ['agent-hook', name, '--agent', self.name]
        marker = hooks.marker(config, identity, 'startup' if startup else 'instruction roots')
        return marker, {'matcher': '^(startup|resume|clear|compact)$', 'hooks': [
            {'type': 'command', 'command': hooks.command(config, args), 'timeout': timeout,
             'statusMessage': marker, 'additionalContextLimit': 1000}]}

    def render(self, path, marker, group, old, **options):
        return hooks.render(path, marker, group, old, **options)

    def current(self, path, marker, group):
        return hooks.current(path, marker, group)

    def remove(self, path, record):
        return hooks.remove(path, record)

    def context(self, text):
        return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}

    def failure(self, message):
        return {'continue': False, 'stopReason': message, 'systemMessage': message}

    def startup_result(self, briefing="", *, skills_changed=False):
        if not briefing:
            return {}
        if STARTUP_BRIEFING_OUTPUT == "systemMessage":
            return {"systemMessage": briefing}
        if STARTUP_BRIEFING_OUTPUT == "additionalContext":
            return self.context(briefing)
        raise Error(f"Unsupported startup briefing output: {STARTUP_BRIEFING_OUTPUT}")


    def validate_skill_name(self, name):
        pass


@dataclass(frozen=True)
class Claude:
    name: str = 'claude'
    entry_name: str = 'CLAUDE.md'
    hook_name: str = 'settings.json'
    shared_settings_format: str | None = 'json'
    command_events: tuple = ('SessionStart', 'SessionEnd', 'PreToolUse', 'PermissionRequest',
                             'PostToolUse', 'PostToolUseFailure', 'PreCompact', 'PostCompact',
                             'SubagentStart', 'SubagentStop', 'UserPromptSubmit', 'Stop')
    hook_timeout_limits: tuple = (('SessionEnd', 60),)
    unmatched_hook_events: tuple = ('UserPromptSubmit', 'Stop')

    def personal_command(self, marker, args):
        from .personal_hooks import direct_command
        return direct_command(marker, args)
    failure_to_stderr: bool = True
    failure_exit_code: int = 2
    notice: str = ("Claude Code hooks are registered in the user settings file; review them with /hooks. "
                   "AEM does not change Claude Code permissions.")

    def defaults(self):
        root = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser().resolve()
        return {'root': str(root), 'skills': str(root / 'skills')}

    def definition(self, config, name, *, startup=False, startup_timeout=10):
        identity = f'{self.name}:startup' if startup else f'{self.name}:{name}'
        marker = hooks.marker(config, identity, 'startup' if startup else 'instruction roots')
        args = (['startup', '--trigger', 'agent-start', '--agent', self.name] if startup else
                ['agent-hook', name, '--agent', self.name])
        command = hooks.command(config, [*args, '--aem-hook-id', marker], preserve_exit=True)
        return marker, {'matcher': '^(startup|resume|clear|compact|fork)$', 'hooks': [
            {'type': 'command', 'command': command, 'timeout': startup_timeout if startup else 10}]}

    def render(self, path, marker, group, old, **options):
        return hooks.render(path, marker, group, old, marker_field='command', **options)

    def current(self, path, marker, group):
        return hooks.current(path, marker, group, marker_field='command')


    def remove(self, path, record):
        return hooks.remove(path, record, marker_field='command')

    def context(self, text):
        # Claude Code injects SessionStart hook stdout as plain context text.
        return text

    def failure(self, message):
        # Claude Code cannot block SessionStart. The CLI writes this to stderr
        # and exits with 2 so the user sees the failure before continuing.
        return message

    def startup_result(self, briefing="", *, skills_changed=False):
        if skills_changed:
            return {'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                          'additionalContext': briefing, 'reloadSkills': True}}
        return briefing

    def validate_skill_name(self, name):
        if name.lower() in ('synced', 'anthropic-skills'):
            raise Error(f'Skill {name}: name is reserved by Claude Code')


PROFILES = {'codex': Codex(), 'claude': Claude()}


def profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise Error(f'Unsupported agent: {name}') from None


def bindings(document):
    values = document.get('agents', {})
    if not isinstance(values, dict):
        raise Error('Machine agents must be a table')
    result = {}
    for name, value in values.items():
        adapter = profile(name)
        if not isinstance(value, dict) or set(value) - {'root', 'skills'}:
            raise Error(f'Invalid agent binding: {name}')
        result[name] = {**adapter.defaults(), **value}
        for path in result[name].values():
            if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
                raise Error(f'Agent {name} paths must be absolute')
    return result


def suffix(name):
    # Keep the default profile's item names concise.
    return '' if name == 'codex' else '@' + name
