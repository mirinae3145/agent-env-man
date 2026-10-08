"""Click entrypoint and command registration for AEM."""

from pathlib import Path

import click

from .cli_runtime import Runtime
from .commands import delivery, installation, device
from .commands.catalog import catalog
from .commands.settings import settings, export_command
from .commands.documentation import docs
from .commands.hooks import hooks
from .model import default_config


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", type=click.Path(path_type=Path), default=default_config,
              help="Machine-local TOML file.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON instead of readable text.")
@click.option("--verbose", is_flag=True, help="Show detailed text reports; cannot be combined with --json.")
@click.pass_context
def cli(ctx, config, json_output, verbose):
    """Install skills and personal instruction bundles from an independent catalog.

    Global --config, --json and --verbose options precede COMMAND.
    """
    # Parsing and help must remain side-effect free. Configuration/state reads
    # and locks belong to the selected command's Runtime.run boundary.
    if json_output and verbose:
        raise click.UsageError("--json and --verbose are mutually exclusive")
    ctx.obj = Runtime(config, json_output, verbose)


for command in (docs, delivery.bootstrap, delivery.update, delivery.publish,
                installation.apply, installation.sync, installation.auto,
                installation.status, installation.detach, installation.locate,
                installation.recover, device.setup, device.self_group,
                device.automation_command, device.startup, device.agent_hook,
                device.full_run, device.self_skill_refresh, catalog, settings, export_command, hooks):
    cli.add_command(command)


def main(argv=None):
    """Run the CLI and return its exit code, including help and usage errors."""
    try:
        return cli.main(args=argv, prog_name="aem", standalone_mode=False) or 0
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
