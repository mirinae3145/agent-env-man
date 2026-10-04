"""Explicit removal of saved personal groups; product trust remains separate."""
import click

from ..cli_runtime import pass_runtime, agent_option, preview_option
from ..model import identifier, Error


@click.group()
def hooks():
    """Manage declared personal command hooks.

    Prepare with bootstrap, register with apply --item NAME, inspect with status
    or locate, and preserve a registration with detach NAME. Registration never
    grants trust; source updates never change installed hook definitions.
    """


@hooks.command()
@click.argument('name', nargs=-1, required=True, metavar='NAME...')
@agent_option
@preview_option
@pass_runtime
def remove(runtime, name, agent, dry_run):
    """Remove only unchanged owned groups, even without a catalog or runtime.

    NAME is a saved personal hook name. Omit --agent to remove all its saved
    agent registrations. Detached, edited or duplicate groups require explicit
    reconciliation; no other groups or preferences are removed. --dry-run is
    offline and preserves files and ownership records.
    """
    try:
        for value in name:
            identifier(value)
    except Error as exc:
        raise click.BadParameter(str(exc), param_hint='NAME') from exc
    from ..personal_hooks import remove as remove_hooks
    return runtime.run(lambda session: (remove_hooks(session.manager, name, agent=agent, dry_run=dry_run), False),
                       maintenance=True)
