"""Shared execution boundary for Click commands and installed callbacks."""

from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import time

import click

from . import self_update
from .agents import PROFILES, profile
from .manager import Manager
from .model import Config, Error, MachineFile, identifier
from .output import format_report
from .storage import State, lock


OPERATION_ERRORS = (Error, OSError, ValueError, subprocess.SubprocessError)


class FiniteNumber(click.ParamType):
    """Reject non-finite durations before configuration or filesystem access."""

    name = "seconds"

    def __init__(self, *, allow_zero=False):
        self.allow_zero = allow_zero

    def convert(self, value, param, ctx):
        try:
            number = float(value)
        except (TypeError, ValueError):
            self.fail("must be a number", param, ctx)
        if not math.isfinite(number) or number < 0 or (number == 0 and not self.allow_zero):
            self.fail("must be finite and " + ("nonnegative" if self.allow_zero else "positive"), param, ctx)
        return number


SECONDS = FiniteNumber()
INTERVAL = FiniteNumber(allow_zero=True)


class AgentName(click.ParamType):
    """Resolve the live profile registry, including injected test profiles."""

    name = "agent"

    def convert(self, value, param, ctx):
        if value not in PROFILES:
            self.fail(f"choose from {', '.join(PROFILES)}", param, ctx)
        return value

    def get_metavar(self, param, ctx):
        return "[" + "|".join(PROFILES) + "]"

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem
        return [CompletionItem(name) for name in PROFILES if name.startswith(incomplete)]


AGENT = AgentName()


def identifier_value(ctx, param, value):
    """Validate repeated integration identifiers as command usage errors."""
    try:
        return tuple(identifier(name) for name in value)
    except Error as exc:
        raise click.BadParameter(str(exc), ctx=ctx, param=param) from exc


@dataclass
class Session:
    manager: Manager
    configuration_error: Exception | None = None

    @property
    def config(self):
        return self.manager.config

    @property
    def state(self):
        return self.manager.state


@dataclass
class Runtime:
    config_path: Path
    json_output: bool = False

    def emit(self, report, *, machine=False):
        if machine and isinstance(report, str):
            click.echo(report)
            return
        click.echo(json.dumps(report, indent=2, ensure_ascii=True)
                   if machine or self.json_output else format_report(report))

    def run(self, operation, *, maintenance=False, missing_ok=False, preview=False,
            status_fallback=False, callback=None, agent=None, output=None):
        """Run an operation returning (report, failed) under the required locks.

        Help and usage parsing finish before this boundary. Preview commands
        opt out of locks only where their existing read-only contract allows it.
        Maintenance reads saved ownership without installation declarations;
        offline status can fall back to it when current declarations are invalid.
        An optional output callable handles specialized successful reports, such
        as plain directory paths for shell integration; errors retain stderr.
        """
        try:
            config = MachineFile(self.config_path, missing_ok=missing_ok)
            try:
                tool_lock = self_update.installation_lock(self_update.validate(config.doc.get("self_update", {})))
            except ValueError:
                tool_lock = None  # Opaque settings must not block offline maintenance.
            # Both locks share the callback budget so installation contention
            # cannot fail immediately or consume a second five-second wait.
            deadline = time.monotonic() + 5 if callback in ("agent-hook", "startup") else None

            def remaining():
                return max(0, deadline - time.monotonic()) if deadline is not None else 0

            with (lock(tool_lock, timeout=remaining(), shared=True) if tool_lock and not preview else nullcontext()), ExitStack() as locks:
                snapshot = None
                if not preview:
                    try:
                        locks.enter_context(lock(config.state_dir, timeout=remaining()))
                    except Error:
                        if callback != 'agent-hook' or not maintenance:
                            raise
                        # Network delivery can hold this lock for much longer
                        # than a SessionStart hook. Location metadata is read-only:
                        # accept only an unchanged, recovery-free saved snapshot.
                        snapshot = {path: path.read_bytes() if path.exists() else None
                                    for path in (self.config_path, config.state_dir / 'state.json')}
                # Re-read after acquiring the lock or capturing the snapshot.
                saved_error = None
                if maintenance:
                    config = MachineFile(self.config_path, missing_ok=missing_ok)
                    state = State(config.state_dir, maintenance=True)
                else:
                    try:
                        config = Config(self.config_path, missing_ok=missing_ok)
                        state = State(config.state_dir)
                    except Error as exc:
                        if not status_fallback:
                            raise
                        config = MachineFile(self.config_path)
                        state = State(config.state_dir, maintenance=True)
                        saved_error = exc
                report, failed = operation(Session(Manager(config, state), saved_error))
                if snapshot is not None:
                    state.ready()
                    if any((path.read_bytes() if path.exists() else None) != data
                           for path, data in snapshot.items()):
                        raise Error('Saved instruction locations changed during lookup; retry after the active command')
                if output is None:
                    self.emit(report, machine=callback is not None)
                else:
                    output(report)
        except OPERATION_ERRORS as exc:
            if callback == "agent-hook":
                adapter = profile(agent)
                failure = adapter.failure(f"AEM instruction root lookup failed: {exc}")
                if adapter.failure_to_stderr:
                    click.echo(failure, err=True)
                else:
                    self.emit(failure, machine=True)
                if adapter.failure_exit_code:
                    raise click.exceptions.Exit(adapter.failure_exit_code) from exc
                return 0
            click.echo(f"aem: {exc}", err=True)
            if callback == "startup":
                self.emit(profile(agent).startup_result() if agent else {}, machine=True)
                return 0
            raise click.exceptions.Exit(1) from exc
        if failed:
            raise click.exceptions.Exit(1)
        return 0


pass_runtime = click.make_pass_decorator(Runtime)


def timeout_option(function):
    return click.option("--git-timeout", "--timeout", "timeout", type=SECONDS, default=30.0, show_default=True,
                        help="Seconds per Git phase.")(function)


def agent_option(function):
    return click.option("--agent", type=AGENT, help="Select an agent destination.")(function)


def item_option(function):
    return click.option("--item", multiple=True, metavar="NAME", help="Select an item; repeat for multiple items.")(function)


def preview_option(function):
    return click.option("--dry-run", is_flag=True, help="Preview without performing the operation.")(function)


def catalog_policy_options(function):
    from .updates import TRIGGERS
    for decorator in reversed((
        click.option("--catalog-trigger", multiple=True, type=click.Choice(("manual", *TRIGGERS)),
                     help="Replace catalog triggers; repeat for multiple events."),
        click.option("--catalog-interval", type=INTERVAL, help="Minimum seconds between automatic catalog attempts."),
        click.option("--catalog-git-timeout", "--catalog-timeout", "catalog_timeout", type=SECONDS, help="Seconds per Git phase for automatic catalog updates."),
    )):
        function = decorator(function)
    return function
