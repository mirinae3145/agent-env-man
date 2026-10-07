"""Installation, inspection, and ownership maintenance commands."""

import click

from .. import automation, self_update
from ..cli_runtime import AGENT, pass_runtime, agent_option, item_option, timeout_option, preview_option
from ..model import Error
from ..updates import run_updates, TRIGGERS


@click.command()
@agent_option
@item_option
@timeout_option
@click.option("--adopt", is_flag=True, help="Record matching existing targets.")
@click.option("--replace", is_flag=True, help="Back up and replace conflicts for explicit --item selections.")
@click.option("--reattach", is_flag=True, help="Allow explicitly selected detached items.")
@preview_option
@pass_runtime
def apply(runtime, agent, item, timeout, adopt, replace, reattach, dry_run):
    """Install prepared local content into selected destinations.

    Omit --item to install non-detached items except personal hooks, which need
    explicit NAME or NAME:hook / NAME:hook@claude selection. Skill, directory,
    and setting IDs are catalog names; directories also accept NAME:directory.
    Instruction IDs are NAME:bundle, NAME:entry, and NAME:hook. Selecting an
    entry or hook also selects its instruction group. Directories remain
    included with --agent because they are independent of agent bindings.
    """
    if adopt and replace:
        raise click.UsageError("--adopt and --replace are mutually exclusive")
    return runtime.run(lambda session: (session.manager.apply(
        item, adopt=adopt, replace=replace, reattach=reattach, dry_run=dry_run, timeout=timeout, agent=agent), False))


@click.command()
@agent_option
@item_option
@timeout_option
@pass_runtime
def sync(runtime, agent, item, timeout):
    """Update sources, then install only if every update succeeds.

    All content sources are updated. --item and --agent filter only the install
    phase; --item uses the same IDs as apply.
    """
    def operation(session):
        session.state.ready()
        updates, failed = session.manager.update(timeout=timeout)
        report = {"updates": updates, "apply": "skipped"}
        if not failed:
            report["apply"] = session.manager.apply(item, timeout=timeout, agent=agent)
        return report, failed
    return runtime.run(operation)


@click.command()
@click.option("--trigger", required=True, type=click.Choice(TRIGGERS), help="External event to process.")
@item_option
@preview_option
@pass_runtime
def auto(runtime, trigger, item, dry_run):
    """Run due skill and directory policies for an external event.

    --item selects catalog names; omission considers all their policies.
    Sources must be prepared. External directory checks do not fetch;
    sync applies their local contents. --dry-run is offline.
    """
    return runtime.run(lambda session: run_updates(session.manager, trigger, item, dry_run=dry_run))


@click.command()
@agent_option
@click.option("--refresh", is_flag=True, help="Fetch remote content status; otherwise stay offline.")
@timeout_option
@pass_runtime
def status(runtime, agent, refresh, timeout):
    """Inspect content, ownership, and device automation."""
    def operation(session):
        report = (session.manager.saved_status(agent=agent, error=session.configuration_error)
                  if session.configuration_error else session.manager.status(refresh=refresh, timeout=timeout, agent=agent))
        for key, inspect in (("automation", automation.status), ("self_update", self_update.status)):
            try:
                report[key] = inspect(session.config)
            except (Error, ValueError) as exc:
                report[key] = {"error": str(exc)}
        if "catalog_automation" in session.state.data:
            report["catalog_automation"] = session.state.data["catalog_automation"]
        return report, False
    return runtime.run(operation, status_fallback=not refresh)


@click.command()
@click.argument("item", nargs=-1, required=True, metavar="NAME...")
@agent_option
@preview_option
@pass_runtime
def detach(runtime, item, agent, dry_run):
    """Preserve installed contents and release ownership."""
    return runtime.run(lambda session: (session.manager.detach(item, dry_run=dry_run, agent=agent), False), maintenance=True)


@click.command()
@click.argument("name")
@click.option("--agent", default="codex", show_default=True, type=AGENT)
@click.option("--source", is_flag=True, help="Locate the current catalog source for editing and publication.")
@click.option("--repo", is_flag=True, help="Locate the prepared source Git checkout root instead of the content subdirectory.")
@click.option("--target", is_flag=True, help="Locate the actual settings file.")
@click.option("--cd", is_flag=True, help="Change directory with the installed shell integration; otherwise print the root.")
@pass_runtime
def locate(runtime, name, agent, source, repo, target, cd):
    """Locate installed content or its prepared source offline.

    NAME is a catalog skill, directory, instruction, setting or personal hook
    name. Skills, directories and instructions default to their saved
    installation, or the prepared source when uninstalled. Directories are
    agent-independent. Settings default to the editable stage; --source
    selects shared content and --target selects the actual application file.
    --repo selects the current source Git checkout root for any agent, with or
    without --source. External folder sources have no registered Git checkout.

    --cd requires setup --shell and a reloaded profile to change the calling
    shell's directory; rerun setup for older shell registrations. Otherwise it
    prints the directory. --cd cannot be combined with global --json.
    """
    if source and target:
        raise click.UsageError("--source and --target are mutually exclusive")
    if repo and target:
        raise click.UsageError("--repo and --target are mutually exclusive")
    if cd and runtime.json_output:
        raise click.UsageError("--cd cannot be combined with --json")
    return runtime.run(lambda session: (session.manager.locate(name, agent, source=source, target=target, repo=repo), False),
                       maintenance=True, output=(lambda report: click.echo(report["root"])) if cd else None)


@click.command()
@pass_runtime
def recover(runtime):
    """Restore the previous target after an interrupted replacement."""
    def operation(session):
        session.manager.recover()
        return {"status": "recovered"}, False
    return runtime.run(operation, maintenance=True)
