"""Explicit commands for the bound catalog, independent of its content."""

from pathlib import Path
from types import SimpleNamespace

import click

from .. import catalog as delivery
from ..cli_runtime import pass_runtime, timeout_option, preview_option
from ..updates import TRIGGERS


@click.group()
def catalog():
    """Inspect, update, or publish the bound catalog."""


def run(runtime, action, *, output=None, **options):
    args = SimpleNamespace(catalog_command=action, **options)
    return runtime.run(lambda session: delivery.command(session.config, session.state, args), output=output)


@catalog.command()
@timeout_option
@pass_runtime
def status(runtime, timeout):
    """Inspect the catalog and its checkout offline."""
    return run(runtime, "status", timeout=timeout)


@catalog.command()
@timeout_option
@click.option("--source", is_flag=True, help="Locate the external original of a copied catalog, even when unavailable.")
@click.option("--cd", is_flag=True, help="Change directory with the installed shell integration; otherwise print the entry directory.")
@pass_runtime
def locate(runtime, timeout, cd, source):
    """Locate the bound catalog entry offline.

    For copied catalogs the default is the managed entry; --source selects
    the original even when missing. Other bindings use the same entry.
    --cd uses the shell integration installed by setup --shell; reload the
    profile after setup. Without it, print the entry directory. --cd cannot
    be combined with global --json.
    """
    if cd and runtime.json_output:
        raise click.UsageError("--cd cannot be combined with --json")
    return run(runtime, "locate", timeout=timeout, source=source,
               output=(lambda report: click.echo(str(Path(report["entry"]).parent))) if cd else None)


@catalog.command()
@timeout_option
@pass_runtime
def update(runtime, timeout):
    """Validate and update the catalog without installing content.

    Git catalogs fast-forward. Copied local catalogs receive their external
    original; local edits are preserved and competing edits require reconciliation.
    """
    return run(runtime, "update", timeout=timeout)


@catalog.command()
@click.option("--from-copy", is_flag=True, help="Explicitly return managed local catalog edits to the external file; conflicts stop without overwriting.")
@click.option("-m", "--message", help="Commit all nonignored catalog checkout changes.")
@preview_option
@timeout_option
@pass_runtime
def publish(runtime, message, dry_run, timeout, from_copy):
    """Publish the whole Git catalog repository, or return local copy edits.

    Local copy bindings require --from-copy and reject --message. Only the
    external local file is written; synchronization remains external. Different
    edits on both sides stop publication for manual reconciliation.

    With --message, commit all nonignored checkout changes. Without it, require
    a clean worktree and push existing commits. --dry-run is offline and does
    not verify remote state. First publication requires a successfully verified
    empty remote; remote errors stop publication.
    """
    return run(runtime, "publish", message=message, dry_run=dry_run, timeout=timeout, from_copy=from_copy)


@catalog.command()
@click.option("--trigger", required=True, type=click.Choice(TRIGGERS), help="External event to process.")
@preview_option
@pass_runtime
def auto(runtime, trigger, dry_run):
    """Run due catalog policy work for an external event."""
    return run(runtime, "auto", trigger=trigger, dry_run=dry_run)
