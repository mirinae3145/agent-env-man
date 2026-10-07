"""Catalog binding, content delivery, and publication commands."""

from pathlib import Path
from types import SimpleNamespace

import click
import tomlkit

from .. import catalog as catalog_delivery
from ..agents import profile
from ..cli_runtime import pass_runtime, timeout_option, preview_option, item_option, catalog_policy_options
from ..manager import Manager
from ..model import Config, Error, absolute, identifier
from ..storage import atomic_write
from ..updates import set_catalog_policy


def bootstrap_skills(config, state, args):
    state.ready()
    document = tomlkit.parse(tomlkit.dumps(config.doc))
    set_catalog_policy(document, args)
    if args.catalog_repository is not None:
        if args.catalog_path is not None or args.catalog is not None:
            raise Error("Git catalog registration cannot be combined with a local catalog path")
        if args.catalog_entry is None:
            raise Error("--catalog-repository requires --catalog-path")
        document["catalog"] = {"type": "git", "repository": args.catalog_repository, "path": args.catalog_entry}
        if args.catalog_branch is not None:
            document["catalog"]["branch"] = args.catalog_branch
        elif config.catalog_source:
            repository = args.catalog_repository
            if Path(repository).expanduser().is_absolute():
                repository = str(absolute(repository))
            if repository == config.catalog_source.git and config.catalog_source.branch:
                document["catalog"]["branch"] = config.catalog_source.branch
    elif args.catalog_entry is not None or args.catalog_branch is not None:
        raise Error("--catalog-path and --catalog-branch require --catalog-repository")
    if args.catalog_path is not None:
        if args.catalog is not None:
            raise Error("Specify the catalog either positionally or with --catalog, not both")
        args.catalog = Path(args.catalog_path)
    if args.catalog is not None:
        document["catalog"] = str(args.catalog.expanduser().resolve())
    if "catalog" not in document:
        raise Error("Use bootstrap /path/to/catalog.toml or --catalog-repository URL --catalog-path PATH")
    if args.checkout_root is not None:
        document["checkout_root"] = str(args.checkout_root.expanduser().resolve())
    roots = document.setdefault("roots", {})
    for value in args.root:
        key, separator, location = value.partition("=")
        if not separator:
            raise Error("--root expects NAME=ABSOLUTE_PATH")
        identifier(key)
        resolved = str(absolute(location))
        if key in config.roots and config.roots[key] != Path(resolved):
            raise Error(f"Root {key} is already configured; detach before relocating installed skills")
        roots[key] = resolved
        if key in ("agent", "skills") and "codex" in document.get("agents", {}):
            document["agents"]["codex"]["root" if key == "agent" else "skills"] = resolved
    defaults = next(iter(config.agents.values())) if config.agents else profile("codex").defaults()
    roots.setdefault("skills", defaults["skills"])
    roots.setdefault("agent", defaults["root"])
    external_names = set()
    for value in args.external:
        key, separator, location = value.partition("=")
        if not separator or not location:
            raise Error("--external expects NAME=PATH")
        identifier(key)
        if key in external_names:
            raise Error(f"Duplicate --external binding: {key}")
        external_names.add(key)
        document.setdefault("external_paths", {})[key] = str(Path(location).expanduser().resolve())
    for value in getattr(args, "setting_target", ()):
        key, separator, location = value.partition("=")
        if not separator or not location:
            raise Error("--setting-target expects NAME=ABSOLUTE_PATH")
        identifier(key)
        target = Path(location).expanduser()
        if not target.is_absolute():
            raise Error("Setting target must be absolute")
        document.setdefault("settings", {})[key] = {"target": str(target)}
    runtime_names = set()
    for value in getattr(args, 'hook_runtime', ()):
        key, separator, location = value.partition('=')
        if not separator or not location:
            raise Error('--runtime expects NAME=ABSOLUTE_EXECUTABLE')
        identifier(key)
        if key in runtime_names:
            raise Error(f'Duplicate runtime binding: {key}')
        runtime_names.add(key)
        from ..personal_hooks import runtime_path
        document.setdefault('runtimes', {})[key] = str(runtime_path(location))
    candidate = Config(config.path, document=document)
    # A remote inventory must be downloaded before its declarations can be
    # checked. Content repositories remain untouched until all preflight passes.
    with catalog_delivery.prepare(candidate, state, timeout=args.timeout) as (candidate, catalog_report):
        if external_names - candidate.external_names:
            raise Error("--external must name an external declared in the catalog")
        if set(args.item) - candidate.sources.keys():
            raise Error("Unknown catalog source selection")
        catalog_delivery.validate(candidate, state)
        for value in getattr(args, "setting_target", ()):
            if value.partition("=")[0] not in candidate._settings:
                raise Error("--setting-target must name a catalog setting")
        manager = Manager(candidate, state)
    atomic_write(config.path, tomlkit.dumps(candidate.doc).encode("utf-8"))
    report, failed = manager.prepare_skills(args.item, timeout=args.timeout)
    result = {"skills": report, "config": str(config.path), "next": "apply --dry-run"}
    if catalog_report:
        result["catalog"] = catalog_report
    return result, failed


@click.command()
@click.argument("catalog_path", required=False, type=click.Path(path_type=Path), metavar="CATALOG")
@click.option("--catalog", type=click.Path(path_type=Path), help="Local catalog file; alternative to CATALOG.")
@click.option("--catalog-repository", help="Git catalog URL or absolute local repository path.")
@click.option("--catalog-path", "catalog_entry", help="Catalog entry relative to its Git repository.")
@click.option("--catalog-branch", help="Catalog branch; otherwise record the remote default.")
@click.option("--checkout-root", type=click.Path(path_type=Path), help="Storage for managed checkouts.")
@click.option("--root", multiple=True, metavar="NAME=PATH", help="Bind a destination root; repeat for multiple roots.")
@click.option("--external", multiple=True, metavar="NAME=PATH", help="Bind an external source; repeat for multiple sources.")
@click.option("--setting-target", multiple=True, metavar="NAME=PATH", help="Bind a setting target file.")
@click.option('--runtime', 'hook_runtime', multiple=True, metavar='NAME=PATH', help='Bind a personal hook runtime to an absolute executable; never install it.')
@item_option
@timeout_option
@catalog_policy_options
@pass_runtime
def bootstrap(runtime, **options):
    """Prepare catalog content and save machine bindings; never install targets.

    Omit CATALOG to reuse the saved binding. --item selects catalog skill,
    directory, instruction, setting or personal hook names, not installation
    component IDs. Omit --item to prepare all declared sources. Existing
    checkouts are not updated. Directories require a named target root;
    bind it with --root NAME=PATH.
    """
    options["catalog_trigger"] = list(options["catalog_trigger"]) or None
    args = SimpleNamespace(**options)
    return runtime.run(lambda session: bootstrap_skills(session.config, session.state, args), missing_ok=True)


@click.command()
@click.argument("source", nargs=-1, metavar="[NAME]...")
@timeout_option
@pass_runtime
def update(runtime, source, timeout):
    """Fetch and fast-forward prepared sources; live links change immediately."""
    return runtime.run(lambda session: session.manager.update(source, timeout=timeout))


@click.command()
@click.argument("source", nargs=-1, required=True, metavar="NAME...")
@click.option("-m", "--message", help="Commit all nonignored checkout changes with this message.")
@click.option("--from-copy", is_flag=True, help="Collect selected managed skill/directory copies before publication; conflicts stop the source group.")
@preview_option
@timeout_option
@pass_runtime
def publish(runtime, source, message, from_copy, dry_run, timeout):
    """Export selected settings and publish whole checkouts by catalog item name.

    NAME selects a catalog skill, directory, instruction, setting or personal
    hook, not a repository or installation component ID. Settings export
    their stage before publication; actual application edits are not collected.
    --from-copy requires installed skill/directory copies for each selected
    name and compares their saved baseline before writing the source. External
    copies publish into their local source folder; transport stays outside AEM.
    Without --from-copy, installed copy edits are not collected.

    With --message, commit all nonignored changes in each selected repository.
    Without it, require a clean worktree and push existing commits. --dry-run
    is offline and does not verify remote state. First publication requires a
    successfully verified empty remote; remote errors stop publication.
    """
    return runtime.run(lambda session: session.manager.publish(source, message=message, from_copy=from_copy, dry_run=dry_run, timeout=timeout))
