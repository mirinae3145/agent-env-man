"""Check that hooks other tools install for themselves are present."""

import json

import click

from ..cli_runtime import pass_runtime
from ..tool_hooks import check, render


@click.command("check-tool-hooks")
@click.option("--agent", "agents", multiple=True, metavar="NAME",
              help="Check only this registered Claude Code agent; repeat for multiple agents.")
@pass_runtime
def check_tool_hooks(runtime, agents):
    """Check the machine's declared tool hooks offline and read-only.

    A tool hook is a hook a tool such as herdr installs for itself; the
    machine configuration declares it under tool_hooks. A tool that is not
    installed is skipped. For an installed tool, every selected Claude Code
    profile must have a hook for the declared event whose command contains the
    declared text. AEM never installs or changes tool hooks. Exit status is 1
    when any hook is missing.
    """
    def operation(session):
        report = check(session.manager.config.doc, selected=agents)
        return report, report['missing'] > 0

    def output(report):
        click.echo(json.dumps(report, indent=2, ensure_ascii=True) if runtime.json_output else render(report))

    return runtime.run(operation, maintenance=True, missing_ok=True, preview=True, output=output)
