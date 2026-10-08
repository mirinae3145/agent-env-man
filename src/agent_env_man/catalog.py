"""Git delivery of the inventory, independent of content delivery.

Bootstrap, catalog commands, and opted-in startup automation contact this repository. Candidate catalogs
are interpreted against final machine paths before their checkout advances.
"""

from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from types import SimpleNamespace

import tomlkit

from .git_source import Git, now
from .model import Config, Error, overlaps
from .storage import exists, is_reparse


def source_for(config):
    source = config.catalog_source
    if source is None:
        raise Error("This command requires a Git catalog; register one with bootstrap --catalog-repository")
    if source.branch is None:
        raise Error("Run bootstrap to record the catalog's default branch")
    return source


def descriptor(git, source, entry, revision="HEAD"):
    """Require a tracked regular file, including on Windows without symlinks."""
    listing = git.run(source.path, "ls-tree", "-z", revision, "--", entry).stdout
    if not listing or listing.split(" ", 1)[0] not in ("100644", "100755"):
        raise Error(f"Catalog needs a tracked regular file: {entry}")


def local_entry(config, git=None):
    """Validate identity and entry ancestry without requiring a clean worktree."""
    source = source_for(config)
    git = git or Git()
    git.validate(source)
    descriptor(git, source, config.doc["catalog"]["path"])
    cursor = config.catalog_path
    while cursor != source.path:
        if cursor.is_symlink() or is_reparse(cursor):
            raise Error(f"Catalog path redirects through a symlink or junction: {cursor}")
        cursor = cursor.parent
    if not config.catalog_path.is_file():
        raise Error(f"Catalog file is missing: {config.catalog_path}")
    return config.catalog_path


def validate(config, state):
    """Validate declarations and existing ownership without fetching content."""
    from .manager import Manager
    protect_storage(config, state)
    config.catalog()
    Manager(config, state).selected()


def protect_storage(config, state):
    if config.catalog_copy_source is not None:
        from .local_catalog import protect_storage as protect_copy
        protect_copy(config, state)
    if config.catalog_source:
        for record in state.data["items"].values():
            if overlaps(config.catalog_source.path, Path(record["target"])):
                raise Error("Catalog checkout overlaps a saved installation target")


def revision_config(config, git, source, revision):
    entry = config.doc["catalog"]["path"]
    descriptor(git, source, entry, revision)
    document = tomlkit.parse(git.run(source.path, "show", f"{revision}:{entry}", strict_utf8=True).stdout)
    return Config(config.path, document=config.doc, catalog_document=document)


@contextmanager
def prepare(config, state, *, timeout=30):
    """Stage a missing catalog and publish it only after caller preflight succeeds.

    Existing checkouts are never pulled/reset. Persisting the machine binding is
    the caller's next step; an interrupted save can retry the validated checkout.
    """
    if config.catalog_copy_source is not None:
        from .local_catalog import prepare as prepare_copy
        with prepare_copy(config, state) as prepared:
            yield prepared
        return
    source = config.catalog_source
    if source is None:
        yield config, None
        return
    protect_storage(config, state)
    git = Git(timeout)
    temporary = None
    try:
        created = not exists(source.path)
        if created:
            source.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".aem-catalog-", dir=source.path.parent))
            options = ("--branch", source.branch) if source.branch else ()
            git.run(None, "clone", "--single-branch", *options, "--", source.git, str(temporary))
        local = replace(source, path=temporary or source.path)
        branch = source.branch or git.run(local.path, "symbolic-ref", "--quiet", "--short", "HEAD").stdout
        local = replace(local, branch=branch)
        git.clean(local)
        document = tomlkit.parse(tomlkit.dumps(config.doc))
        document["catalog"]["branch"] = branch
        config = Config(config.path, document=document)
        revision = git.run(local.path, "rev-parse", "HEAD").stdout
        candidate = revision_config(config, git, local, revision)
        report = {"status": "cloned" if created else "already-prepared", "checkout": str(source.path),
                  "entry": str(config.catalog_path), "repository": source.git, "branch": branch, "revision": revision}
        # The caller also checks explicit item/external selections before rename.
        yield candidate, report
        git.clean(local)
        if git.run(local.path, "rev-parse", "HEAD").stdout != revision:
            raise Error("Catalog changed during bootstrap; retry")
        if temporary:
            if exists(source.path):
                raise Error("Catalog checkout appeared while cloning; refusing replacement")
            os.rename(temporary, source.path)
            temporary = None
    finally:
        if temporary:
            # Git objects can be read-only on Windows, including after a failed clone.
            def writable_retry(operation, path, error):
                os.chmod(path, stat.S_IWRITE)
                operation(path)
            shutil.rmtree(temporary, onerror=writable_retry)


def command(config, state, args):
    """Run a catalog operation; never install or update its declared content."""
    action = args.catalog_command
    source = config.catalog_source
    if action == "auto":
        return run_auto(config, state, args.trigger, dry_run=args.dry_run)
    if config.catalog_copy_source is not None and action != "auto":
        from .local_catalog import command as copy_command
        return copy_command(config, state, args)
    if getattr(args, "from_copy", False):
        raise Error("--from-copy requires a local copy catalog binding")
    if action == "locate":
        if source:
            local_entry(config, Git(args.timeout))
        elif config.catalog_path is None or not config.catalog_path.is_file():
            raise Error("No readable local catalog is bound")
        return {"entry": str(config.catalog_path), "checkout": str(source.path) if source else None,
                "repository": source.git if source else None}, False
    if action == "status":
        report = {"entry": str(config.catalog_path) if config.catalog_path else None,
                  "checkout": str(source.path) if source else None, "repository": source.git if source else None,
                  "automation": state.data.get("catalog_automation", {})}
        try:
            if source:
                source = source_for(config)
                git = Git(args.timeout)
                report.update(git.publication(source))
                report["revision"] = git.run(source.path, "rev-parse", "HEAD").stdout
            config.catalog()
            report["status"] = "ready" if config.catalog_path else "unbound"
        except (Error, OSError, ValueError) as exc:
            report.update(status="unavailable", error=str(exc))
        return report, False
    state.ready()
    source = source_for(config)
    git = Git(args.timeout)
    report = {"checkout": str(source.path), "entry": str(config.catalog_path),
              "repository": source.git, "branch": source.branch, "status": "planned"}
    try:
        if action == "publish":
            if args.message is not None and not args.message.strip():
                raise Error("--message must not be empty")
            report.update(git.publication(source))
            validate(config, state)
            if not args.dry_run:
                git.publish(source, report, message=args.message)
        else:
            git.clean(source)
            previous = git.run(source.path, "rev-parse", "HEAD").stdout
            revision = git.fetch(source)
            report.update(last_fetch=now(), observed_revision=revision, previous_revision=previous)
            relation = git.relation(source)
            if relation not in ("behind", "equal-at-last-fetch"):
                raise Error(f"catalog: {relation}; reconcile Git history manually")
            candidate = revision_config(config, git, source, revision)
            validate(candidate, state)
            git.clean(source)
            if git.run(source.path, "rev-parse", "HEAD").stdout != previous:
                raise Error("Catalog changed during update; retry")
            git.fast_forward(source, revision)
            report.update(status="updated", revision=revision, last_update=now())
    except (Error, OSError, ValueError) as exc:
        report.update(status="failed", error=str(exc))
    if "last_fetch" in report:
        # A separate record avoids collisions with a skill literally named catalog.
        state.data["catalog"] = {key: report[key] for key in
                                 ("repository", "branch", "last_fetch", "observed_revision", "revision",
                                  "last_update", "last_publish", "error") if key in report}
        state.save()
    return report, report["status"] == "failed"


def run_auto(config, state, trigger, *, dry_run=False):
    """Update only the bound catalog under the caller's configuration lock.

    The device policy lives outside the file it updates. Record attempts before
    remote access; explicit catalog commands neither read nor reset this clock.
    A changed binding starts a new clock, independently of skill/source names.
    """
    from .updates import TRIGGERS
    if trigger not in TRIGGERS:
        raise Error(f'Unknown automatic update trigger: {trigger}')
    policy = config.catalog_update
    report = {'policy': policy, 'status': 'not-triggered'}
    if config.automation['mode'] == 'full':
        raise Error('Use automation --trigger EVENT in full mode')
    if config.automation['mode'] == 'off' or trigger not in policy['trigger']:
        return report, False
    state.ready()
    source = source_for(config)
    binding = {'repository': source.git, 'branch': source.branch, 'entry': config.doc['catalog']['path']}
    previous = state.data.get('catalog_automation', {})
    current = time.time()
    if (previous.get('binding') == binding and 'last_attempt' in previous
            and current - previous['last_attempt'] < policy['min_interval']):
        report['status'] = 'throttled'
        return report, False
    report['status'] = 'planned'
    if dry_run:
        return report, False
    attempt = {'binding': binding, 'last_attempt': current, 'trigger': trigger, 'status': 'running'}
    state.data['catalog_automation'] = attempt
    state.save()
    try:
        outcome, failed = command(config, state, SimpleNamespace(catalog_command='update', timeout=policy['timeout']))
        report.update(status=outcome['status'], outcome=outcome)
        attempt['status'] = outcome['status']
        if failed:
            attempt['error'] = outcome['error']
        else:
            attempt['last_success'] = time.time()
    except (Error, OSError, ValueError) as exc:
        failed = True
        report.update(status='failed', error=str(exc))
        attempt.update(status='failed', error=str(exc))
    state.save()
    return report, failed
