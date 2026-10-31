"""Read-only comparison of two agent profiles."""

import json

import click

from ..cli_runtime import pass_runtime
from ..profile_compare import compare as compare_profiles, render, resolve


@click.command()
@click.argument("left")
@click.argument("right")
@click.option("--expect", multiple=True, metavar="ITEM",
              help="Mark a difference as intended, naming the item as the report prints it; repeat for multiple items.")
@click.option("--values", "show_values", is_flag=True,
              help="Show values instead of digests; settings can contain secrets.")
@pass_runtime
def compare(runtime, left, right, expect, show_values):
    """Compare two Claude Code profiles offline and read-only.

    LEFT and RIGHT are registered agent names (such as claude and claude-lab)
    or absolute profile root paths. Settings fields, hook groups by owner,
    skill links, output styles, the instruction entry and installed plugin
    names are compared; profile-specific paths are normalized first.
    Differences are digests unless --values is given. Credentials, sessions
    and plugin data are never read. Nothing is written.
    """
    def operation(session):
        report = compare_profiles(resolve(session.manager.config.doc, left),
                                  resolve(session.manager.config.doc, right),
                                  expect=expect, show_values=show_values)
        return report, False

    def output(report):
        click.echo(json.dumps(report, indent=2, ensure_ascii=True) if runtime.json_output else render(report))

    return runtime.run(operation, maintenance=True, missing_ok=True, preview=True, output=output)
