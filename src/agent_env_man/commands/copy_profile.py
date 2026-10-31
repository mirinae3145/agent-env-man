"""Copy a Claude Code profile into a new independent root."""

import json
import os

import click

from ..cli_runtime import pass_runtime
from ..profile_compare import resolve
from ..profile_copy import apply, plan, render, report


@click.command("copy-profile")
@click.argument("source")
@click.argument("target")
@click.option("--set", "sets", multiple=True, metavar="FIELD=VALUE",
              help="Set a settings field in the copy (dotted path, JSON value or plain text); repeat for multiple fields.")
@click.option("--write", is_flag=True, help="Create the profile; without it only the plan is shown.")
@pass_runtime
def copy_profile(runtime, source, target, sets, write):
    """Copy a Claude Code profile's reusable state into a new, independent root.

    SOURCE is a registered agent name or an absolute profile root; TARGET is
    the new root, which must not exist or must be empty. Settings fields,
    the instruction entry, output styles, skill links and hook scripts are
    copied and the source root in paths is replaced by TARGET. Credentials,
    sessions, history, plugins and AEM-generated hook groups are not copied.
    After writing, the copy is compared with the source. AEM machine
    configuration is never changed; register TARGET as an agent and apply to
    give it its own AEM hooks.
    """
    def operation(session):
        managed = {os.path.normpath(record['target']) for record in session.manager.state.data.get('items', {}).values()
                   if isinstance(record.get('target'), str)}
        copy = plan(resolve(session.manager.config.doc, source), target, sets, managed)
        if write:
            apply(copy)
        return report(copy, write), False

    def output(result):
        click.echo(json.dumps(result, indent=2, ensure_ascii=True) if runtime.json_output else render(result))

    return runtime.run(operation, maintenance=True, missing_ok=True, preview=not write, output=output)
