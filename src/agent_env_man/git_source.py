"""Git delivery, independent of target installation modes except live-link guards."""

from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import time

from .model import Error, Source


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Git:
    def __init__(self, timeout: float = 30, *, fetch_cache=None):
        self.fetch_cache = fetch_cache
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout

    def run(self, path: Path | None, *args: str, check: bool = True, strict_utf8: bool = False) -> subprocess.CompletedProcess:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Error("Git operation timed out")
        command = ["git", "-c", "credential.interactive=false", "-c", "core.hooksPath=" + os.devnull,
                   "-c", "core.fsmonitor=false", "-c", "submodule.recurse=false"]
        if path is not None:
            command += ["-C", str(path)]
        command += list(args)
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never", GIT_LITERAL_PATHSPECS="1",
                   GIT_OPTIONAL_LOCKS="0")
        # Existing SSH_COMMAND customizations remain usable, but cannot prompt.
        env["GIT_SSH_COMMAND"] = env.get("GIT_SSH_COMMAND", "ssh") + " -oBatchMode=yes"
        kwargs = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL, env=env, **kwargs)
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.kill()
            process.communicate()
            raise Error("Git operation timed out; checkout may need inspection") from exc
        result = subprocess.CompletedProcess(command, process.returncode,
                                             stdout.decode("utf-8", errors="strict" if strict_utf8 else "replace").strip(),
                                             stderr.decode("utf-8", errors="replace").strip())
        if check and result.returncode:
            raise Error(f"Git {args[0]} failed: {result.stderr or result.stdout}")
        return result

    def validate_checkout(self, source: Source):
        """Check repository identity without contacting the remote."""
        top = self.run(source.path, "rev-parse", "--show-toplevel").stdout
        if Path(top).resolve() != source.path:
            raise Error(f"{source.name}: source path must be the checkout root")

    def validate(self, source: Source):
        self.validate_checkout(source)
        remote = self.run(source.path, "remote", "get-url", "origin").stdout
        if remote != source.git:
            raise Error(f"{source.name}: origin differs from the registered Git URL")
        branch = self.run(source.path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if branch.returncode or branch.stdout != source.branch:
            raise Error(f"{source.name}: expected attached branch {source.branch}")

    def clean(self, source: Source):
        """Require unchanged tracked content and no nonignored local additions.

        Ignored runtime files may coexist with a managed checkout. They remain
        local contents, and fast_forward separately protects them from incoming
        tracked paths rather than treating every cache as an update conflict.
        """
        self.validate(source)
        if self.run(source.path, "status", "--porcelain", "--untracked-files=all").stdout:
            raise Error(f"{source.name}: dirty checkout; commit or reconcile changes explicitly")
        self.idle(source)

    def fast_forward(self, source: Source, revision: str):
        """Advance without overwriting ignored local files or stashing edits."""
        # Git overwrites ignored files by default, even on a fast-forward.
        # The checkout may contain runtime caches, so retain Git's final collision
        # check at the mutation itself rather than relying on a prior path scan.
        self.run(source.path, "merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", revision)

    def idle(self, source: Source):
        """Reject incomplete Git operations without requiring a clean worktree."""
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            name = self.run(source.path, "rev-parse", "--git-path", marker).stdout
            location = Path(name)
            if not location.is_absolute():
                location = source.path / location
            if location.exists():
                raise Error(f"{source.name}: unfinished Git operation ({marker})")

    def publication(self, source: Source) -> dict:
        """Inspect the entire checkout offline, using the last fetched remote ref."""
        self.validate(source)
        self.idle(source)
        destinations = self.run(source.path, "remote", "get-url", "--push", "--all", "origin").stdout.splitlines()
        if destinations != [source.git]:
            raise Error(f"{source.name}: origin push destination differs from the registered Git URL")
        relation = self.relation(source)
        commits = []
        if relation != "unknown":
            commits = self.run(source.path, "log", "--format=%H %s",
                               f"refs/remotes/origin/{source.branch}..HEAD").stdout.splitlines()
        return {"branch": source.branch, "remote_relation": relation,
                "changes": self.run(source.path, "status", "--porcelain=v1", "--untracked-files=all").stdout,
                "diff": self.run(source.path, "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--").stdout,
                "commits": commits}

    def publication_preflight(self, source: Source) -> str | None:
        """Return the fetched branch revision, or None for a verified empty remote.

        Inspect all advertised refs, including tags, before allowing first
        publication. Authentication/transport failures and a missing branch in
        a populated remote are errors, never evidence of an empty repository.
        This check also runs before settings export can change the checkout.
        """
        self.publication(source)
        self.run(source.path, "check-ref-format", "refs/heads/" + source.branch)
        listing = self.run(source.path, "ls-remote", "--refs", "origin").stdout
        if not listing:
            return None
        refs = {line.split("\t", 1)[1] for line in listing.splitlines() if "\t" in line}
        if "refs/heads/" + source.branch not in refs:
            raise Error(f"{source.name}: registered remote branch {source.branch} is missing; remote is not empty")
        return self.fetch(source)

    def publish(self, source: Source, report: dict, *, message=None):
        """Commit all nonignored changes when requested, then push the selected branch.

        Remote verification precedes staging; populated remotes are fetched.
        Failure after staging/commit preserves that work for inspection and retry;
        publication is not a transaction and never rewrites local or remote history.
        """
        if report["changes"] and message is None:
            raise Error(f"{source.name}: uncommitted changes; supply --message to commit the whole checkout")
        observed = self.publication_preflight(source)
        report.update(last_fetch=now())
        report.update(self.publication(source))
        if observed is None:
            # Cached tracking refs may survive deletion of the remote's refs.
            # They are not a comparison base for verified first publication.
            report.update(initial_publish=True, remote_relation="unknown",
                          commits=self.run(source.path, "log", "--format=%H %s", "HEAD").stdout.splitlines())
        else:
            report["observed_revision"] = observed
            if report["remote_relation"] not in ("ahead", "equal-at-last-fetch"):
                raise Error(f"{source.name}: {report['remote_relation']}; reconcile Git history manually")
        if report["changes"]:
            if message is None:
                raise Error(f"{source.name}: checkout changed; supply --message or commit explicitly")
            self.run(source.path, "add", "--all", "--", ".")
            staged = self.run(source.path, "diff", "--cached", "--quiet", check=False)
            if staged.returncode not in (0, 1):
                raise Error(f"{source.name}: cannot inspect staged changes")
            if staged.returncode:
                self.run(source.path, "commit", "-m", message)
                report["created_commit"] = self.run(source.path, "rev-parse", "HEAD").stdout
        self.validate(source)
        self.idle(source)
        revision = self.run(source.path, "rev-parse", "HEAD").stdout
        # Pin the reviewed commit and refspec; do not inherit push.default,
        # matching branches, followTags, or a configured mirror push.
        self.run(source.path, "-c", "remote.origin.mirror=false", "push", "--porcelain", "--no-follow-tags",
                 "origin", f"{revision}:refs/heads/{source.branch}")
        report.update(status="published", revision=revision, observed_revision=revision, last_publish=now())

    def fetch(self, source: Source) -> str:
        self.validate(source)
        self.run(source.path, "check-ref-format", "refs/heads/" + source.branch)
        key = (source.path, source.git, source.branch, self.timeout)
        if self.fetch_cache is not None and key in self.fetch_cache:
            result = self.fetch_cache[key]
            if isinstance(result, Exception):
                raise Error(str(result))
            return result
        try:
            # A forced remote-tracking update is observational; HEAD is never reset.
            self.run(source.path, "fetch", "--no-tags", "origin",
                     f"+refs/heads/{source.branch}:refs/remotes/origin/{source.branch}")
            result = self.run(source.path, "rev-parse", "refs/remotes/origin/" + source.branch).stdout
        except (Error, OSError, ValueError) as exc:
            if self.fetch_cache is not None:
                self.fetch_cache[key] = exc
            raise
        if self.fetch_cache is not None:
            self.fetch_cache[key] = result
        return result

    def relation(self, source: Source, *, revision: str | None = None) -> str:
        """Compare HEAD with a pinned observation or the current tracking ref."""
        reference = revision if revision is not None else "refs/remotes/origin/" + source.branch
        result = self.run(source.path, "rev-list", "--left-right", "--count",
                          f"HEAD...{reference}", check=False)
        if result.returncode:
            return "unknown"
        ahead, behind = map(int, result.stdout.split())
        return "diverged" if ahead and behind else "ahead" if ahead else "behind" if behind else "equal-at-last-fetch"

    def guard_links(self, source: Source, revision: str, records: dict):
        for key, record in records.items():
            shared_item = (record.get("kind") in ("skill", "directory", "instruction", "instruction-entry")
                            and record.get("source") == str(source.path / record["relative"]))
            if (record.get("source_name") != source.name and not shared_item) or record.get("detached") or record["mode"] != "link":
                continue
            if str(source.path / record["relative"]) != record["source"]:
                raise Error(f"{key}: source path moved; detach before reconfiguration")
            relative = record["relative"]
            if record.get("kind") == "skill":
                self.skill_descriptor(source, relative, revision)
            if record.get("kind") == "instruction":
                self.instruction_descriptor(source, relative, record["entry"], revision)
            if record.get("kind") == "directory":
                self.directory_descriptor(source, relative, revision)
            if relative == "." and record.get("kind") in ("skill", "directory", "instruction"):
                mode = "040000"
            else:
                listing = self.run(source.path, "ls-tree", "-z", revision, "--", relative).stdout
                mode = listing.split(" ", 1)[0] if listing else ""
            allowed = ("040000",) if record["directory"] else ("100644", "100755")
            if mode not in allowed:
                raise Error(f"{key}: incoming commit removes or changes the kind of a live link source; detach first")
            if record["directory"] and record.get("kind") != "skill":
                pathspec = () if relative == "." else (relative,)
                tree = self.run(source.path, "ls-tree", "-rz", revision, "--", *pathspec).stdout
                if any(entry.split(" ", 1)[0] not in ("100644", "100755") for entry in tree.split("\0") if entry):
                    raise Error(f"{key}: incoming linked directory contains a symlink or submodule")

    def directory_descriptor(self, source, relative, revision="HEAD"):
        """Require a Git tree of regular files without imposing an entry document."""
        if relative != ".":
            listing = self.run(source.path, "ls-tree", "-z", revision, "--", relative).stdout
            if not listing or listing.split(" ", 1)[0] != "040000":
                raise Error(f"{source.name}: directory must be a tracked Git tree: {relative}")
        pathspec = () if relative == "." else (relative,)
        tree = self.run(source.path, "ls-tree", "-rz", revision, "--", *pathspec).stdout
        if any(entry.split(" ", 1)[0] not in ("100644", "100755") for entry in tree.split("\0") if entry):
            raise Error(f"{source.name}: directory contains a Git symlink or submodule")

    def instruction_descriptor(self, source, relative, entry, revision="HEAD"):
        """Validate the entry and complete regular-file tree before publishing Git content."""
        descriptor = entry if relative == "." else relative + "/" + entry
        listing = self.run(source.path, "ls-tree", "-z", revision, "--", descriptor).stdout
        if not listing or listing.split(" ", 1)[0] not in ("100644", "100755"):
            raise Error(f"{source.name}: instruction needs a tracked regular entry: {descriptor}")
        pathspec = () if relative == "." else (relative,)
        tree = self.run(source.path, "ls-tree", "-rz", revision, "--", *pathspec).stdout
        if any(e.split(" ", 1)[0] not in ("100644", "100755") for e in tree.split("\0") if e):
            raise Error(f"{source.name}: instruction bundle contains a Git symlink or submodule")

    def skill_descriptor(self, source: Source, relative: str, revision: str = "HEAD"):
        """Require a tracked descriptor and a skill tree of regular Git files.

        Inspect Git modes too: Windows can check out Git symlinks as ordinary
        text files, so filesystem inspection alone cannot enforce this contract.
        """
        descriptor = "SKILL.md" if relative == "." else relative + "/SKILL.md"
        listing = self.run(source.path, "ls-tree", "-z", revision, "--", descriptor).stdout
        if not listing or listing.split(" ", 1)[0] not in ("100644", "100755"):
            raise Error(f"{source.name}: skill needs a tracked regular {descriptor} at {revision}")
        pathspec = () if relative == "." else (relative,)
        tree = self.run(source.path, "ls-tree", "-rz", revision, "--", *pathspec).stdout
        if any(entry.split(" ", 1)[0] not in ("100644", "100755") for entry in tree.split("\0") if entry):
            raise Error(f"{source.name}: skill contains a Git symlink or submodule")

    def update(self, source: Source, records: dict, source_state: dict, *, validate_candidate=None):
        self.clean(source)
        candidate = self.fetch(source)
        source_state.update(last_fetch=now(), observed_revision=candidate)
        relation = self.relation(source, revision=candidate)
        if relation in ("ahead", "diverged", "unknown"):
            raise Error(f"{source.name}: {relation}; reconcile Git history manually")
        self.guard_links(source, candidate, records)
        if validate_candidate is not None:
            validate_candidate(self, source, candidate)
        self.clean(source)
        self.fast_forward(source, candidate)
        source_state.update(last_update=now(), revision=candidate, error=None)

    def tracked_payload(self, source: Source, relative: str):
        """Require a tracked payload root; local ignored contents remain part of its tree."""
        listing = self.run(source.path, "ls-tree", "-z", "HEAD", "--", relative).stdout
        if not listing or listing.split(" ", 1)[0] not in ("040000", "100644", "100755"):
            raise Error(f"{source.name}: payload must be a tracked regular file or directory: {relative}")
