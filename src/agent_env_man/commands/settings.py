"""Explicit settings-stage editing and source export commands."""

import click

from ..cli_runtime import pass_runtime, preview_option
from ..model import Error
from ..settings import Settings, parse_path


def field_path(ctx, param, value):
    try:
        if param.multiple:
            return tuple(parse_path(v) for v in value)
        return parse_path(value)
    except Error as exc:
        raise click.BadParameter(str(exc), ctx=ctx, param=param) from exc


@click.group()
def settings():
    """Prepare, collect, release, and resolve staged settings fields.

    NAME is a catalog setting name. These commands edit a local stage; apply
    writes it to the application, export writes it to the shared source, and
    update receives shared changes. Collection of application edits is explicit.
    """


@settings.command()
@click.argument("name")
@preview_option
@pass_runtime
def prepare(runtime, name, dry_run):
    """Initialize a stage from an already prepared source, preserving edits."""
    def operation(session):
        service = Settings(session.manager)
        return service.prepare(service.item(name), dry_run=dry_run), False
    return runtime.run(operation, preview=dry_run)


@settings.command()
@click.argument("name")
@click.option("--path", multiple=True, callback=field_path, help='Add or reclaim a field; repeat JSON string-array paths, e.g. ["section","key"].')
@preview_option
@pass_runtime
def collect(runtime, name, path, dry_run):
    """Collect changes to managed fields from the actual settings file.

    Without --path, collect only already managed fields. Use --path to add or
    reclaim fields. Collection updates the stage, not the shared source.
    """
    return runtime.run(lambda s: (Settings(s.manager).collect(name, path, dry_run=dry_run), False), preview=dry_run)


@settings.command()
@click.argument("name")
@click.option("--path", required=True, callback=field_path, help="Field path as a JSON string array.")
@preview_option
@pass_runtime
def release(runtime, name, path, dry_run):
    """Prepare explicit management release, preserving the actual value."""
    return runtime.run(lambda s: (Settings(s.manager).release(name, path, dry_run=dry_run), False), preview=dry_run)


@settings.command()
@click.argument("name")
@click.option("--path", required=True, callback=field_path, help="Conflict field path as a JSON string array.")
@click.option("--take", required=True, type=click.Choice(("local", "shared", "edited")),
              help="Choose the local stage, incoming shared value, or manually edited stage.")
@preview_option
@pass_runtime
def resolve(runtime, name, path, take, dry_run):
    """Resolve a shared field conflict or accept a manually edited value."""
    return runtime.run(lambda s: (Settings(s.manager).resolve(name, path, take, dry_run=dry_run), False), preview=dry_run)


@click.command(name="export")
@click.argument("names", nargs=-1, required=True)
@preview_option
@pass_runtime
def export_command(runtime, names, dry_run):
    """Gather copies and settings into sources locally (publish --local)."""
    return runtime.run(lambda s: s.manager.publish(names, local=True, dry_run=dry_run))
