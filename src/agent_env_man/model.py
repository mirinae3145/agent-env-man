"""Independent catalog declarations and machine-local bindings."""

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re

import tomlkit


class Error(Exception):
    """An actionable configuration, ownership, or operation failure."""


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise Error(f"Invalid identifier: {value!r}")
    return value


def relative(value: str) -> Path:
    # No evaluation, Windows drive syntax, or platform-dependent separators.
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        raise Error(f"Expected a literal relative path using /: {value!r}")
    return Path(*PurePosixPath(value).parts)


def absolute(value: str) -> Path:
    if not isinstance(value, str):
        raise Error("Machine paths must be strings")
    result = Path(value).expanduser()
    if not result.is_absolute():
        raise Error(f"Machine paths must be absolute or start with ~/: {value}")
    return result.resolve()


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def default_config() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "agent-env-man/machine.toml"


@dataclass(frozen=True)
class Source:
    name: str
    path: Path
    git: str | None
    branch: str | None


@dataclass(frozen=True)
class Item:
    source_name: str
    id: str
    relative: str
    source: Path
    target: Path
    mode: str
    kind: str
    entry: str | None = None
    agent: str = "codex"
    agents: tuple[str, ...] = ()
    preserve_symlinks: bool = False
    link_target: Path | None = None

    @property
    def link_destination(self) -> Path:
        return self.link_target if self.link_target is not None else self.source

    @property
    def key(self) -> str:
        return self.id if self.kind == "skill" else f"{self.source_name}:{self.id}"


class MachineFile:
    """Read the machine document without interpreting installation declarations.

    Teardown needs its location and, for setup removal, a lossless document to
    edit. Unknown fields and schema versions are deliberately left untouched.
    """
    def __init__(self, path: Path, *, missing_ok: bool = False, document=None):
        self.path = path.expanduser().resolve()
        self.state_dir = self.path.parent / (self.path.name + ".state")
        self.raw = None
        if document is not None:
            self.doc = document
        elif not self.path.exists() and missing_ok:
            self.doc = tomlkit.parse('version = 1\n')
        else:
            try:
                self.raw = self.path.read_bytes()
                self.doc = tomlkit.parse(self.raw.decode("utf-8"))
            except (OSError, ValueError) as exc:
                raise Error(f"Cannot read machine config {self.path}: {exc}") from exc


class Config(MachineFile):
    def __init__(self, path: Path, *, missing_ok: bool = False, document=None, catalog_document=None):
        super().__init__(path, missing_ok=missing_ok, document=document)
        version = self.doc.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            raise Error("Unsupported machine config version")
        unknown = set(self.doc) - {"version", "catalog", "checkout_root", "roots", "agents", "external_paths", "modes", "setup", "self_update", "catalog_update", "automation", "settings", "runtimes"}
        if unknown:
            raise Error("Unknown machine fields: " + ", ".join(sorted(unknown)))
        if not isinstance(self.doc.get("roots", {}), dict):
            raise Error("roots must be a TOML table")
        if not isinstance(self.doc.get("external_paths", {}), dict):
            raise Error("external_paths must be a TOML table")
        for name, value in self.doc.get("external_paths", {}).items():
            identifier(name)
            absolute(value)
        setup = self.doc.get("setup", {})
        if not isinstance(setup, dict) or set(setup) - {"shells", "executable", "startup_hook_timeout"}:
            raise Error("Machine setup accepts only shells, executable, and startup_hook_timeout")
        from .updates import policy_fields
        self.startup_hook_timeout = setup.get("startup_hook_timeout", 10)
        policy_fields({"timeout": self.startup_hook_timeout}, "setup.startup_hook_timeout")
        shells = setup.get("shells", {})
        if not isinstance(shells, dict) or any(
                name not in ("bash", "zsh", "powershell") or not isinstance(path, str)
                or not Path(path).is_absolute() for name, path in shells.items()):
            raise Error("Setup shells must map supported shell names to absolute profile paths")
        if "executable" in setup:
            absolute(setup["executable"])
        from .self_update import validate
        try:
            validate(self.doc.get("self_update", {}))
        except ValueError as exc:
            raise Error(str(exc)) from exc
        self.roots = {identifier(k): absolute(v) for k, v in self.doc.get("roots", {}).items()}
        from .agents import bindings
        self.agents = bindings(self.doc)
        if not isinstance(self.doc.get('runtimes', {}), dict):
            raise Error('Machine runtimes must map names to absolute executable paths')
        from .personal_hooks import runtime_path
        self.runtimes = {identifier(k): str(runtime_path(v)) for k, v in self.doc.get('runtimes', {}).items()}
        for name, paths in self.agents.items():
            for category, field in (("agent", "root"), ("skills", "skills")):
                key, path = f"aem-{category}-{name}", absolute(paths[field])
                if key in self.roots and self.roots[key] != path:
                    raise Error(f"Root {key} conflicts with the agent binding")
                self.roots[key] = path
        self.catalog_path = None
        self.catalog_source = None
        # Candidate revisions can be validated against final device paths before
        # moving the catalog checkout. This input never changes path resolution.
        self._catalog_document = catalog_document
        self._catalog = None
        self._repositories = {}
        self._instructions = {}
        self._settings = {}
        self._hooks = {}
        self._directories = {}
        self._update_policies = {}
        self.checkout_root = absolute(self.doc["checkout_root"]) if "checkout_root" in self.doc else self.path.parent / (self.path.name + ".checkouts")
        if overlaps(self.checkout_root, self.path) or overlaps(self.checkout_root, self.state_dir):
            raise Error("Checkout storage must be separate from machine config and state")
        if "catalog" in self.doc:
            value = self.doc["catalog"]
            if isinstance(value, dict):
                if set(value) - {"type", "repository", "branch", "path"} or value.get("type", "git") != "git":
                    raise Error("Git catalog accepts only type, repository, branch, and path")
                self._validate_repository(value, "Catalog")
                entry = relative(value.get("path"))
                checkout = self.path.parent / (self.path.name + ".catalog")
                if checkout.resolve() != checkout:
                    raise Error("Catalog checkout must not redirect through a symlink or junction")
                protected = [self.path, self.state_dir, self.checkout_root]
                protected.extend(absolute(p) for p in self.doc.get("external_paths", {}).values())
                if any(overlaps(checkout, p) for p in protected):
                    raise Error("Catalog checkout must be separate from content sources and manager storage")
                repository = value["repository"]
                if Path(repository).expanduser().is_absolute():
                    repository = str(absolute(repository))
                self.catalog_source = Source("catalog", checkout, repository, value.get("branch"))
                self.catalog_path = checkout / entry
            elif not isinstance(value, str) or not value:
                raise Error("catalog must name an inventory file")
            else:
                location = Path(value).expanduser()
                self.catalog_path = (location if location.is_absolute() else self.path.parent / location).resolve()
            if overlaps(self.catalog_path, self.state_dir) or self.catalog_path == self.path:
                raise Error("Catalog must be separate from machine config and state")
            if overlaps(self.catalog_path, self.checkout_root):
                raise Error("Keep the local catalog outside managed checkouts")
        from .updates import catalog_policy
        self.catalog_update = catalog_policy(self.doc.get("catalog_update", {}))
        if self.catalog_update['trigger'] != ['manual'] and self.catalog_source is None:
            raise Error('Automatic catalog updates require a Git catalog binding')
        from .automation import policy, runtime
        self.automation = policy(self.doc.get('automation', {}))
        if self.automation['mode'] == 'full':
            runtime(self.doc.get('self_update', {}))
        self.modes = self.doc.get("modes", {})
        if not isinstance(self.modes, dict) or any(v not in ("link", "copy") for v in self.modes.values()):
            raise Error("Machine modes must map skill, directory, or instruction names to link or copy")
        for name in self.modes:
            identifier(name)

    @property
    def external_names(self) -> set[str]:
        """Return the logical external sources declared by the bound catalog."""
        self.catalog()
        return set(getattr(self, "_external_names", ()))

    def catalog(self) -> dict:
        """Load lazily so detach/recovery remain usable when inventory is missing."""
        if self._catalog is not None:
            return self._catalog
        if self.catalog_path is None:
            return {}
        try:
            if self._catalog_document is not None:
                document = self._catalog_document
            else:
                if self.catalog_source:
                    from .catalog import local_entry
                    local_entry(self)
                document = tomlkit.parse(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Error(f"Cannot read skill catalog {self.catalog_path}: {exc}") from exc
        from .catalog_schema import normalize
        document = normalize(document)
        skills = document["skills"]
        repositories = document["repositories"]
        externals = document["externals"]
        instructions = document["instructions"]
        settings = document["settings"]
        declared_hooks = document['hooks']
        directories = document['directories']
        machine_settings = self.doc.get("settings", {})
        if not isinstance(machine_settings, dict):
            raise Error("Machine settings must be a table")
        for name, binding in machine_settings.items():
            identifier(name)
            if not isinstance(binding, dict) or set(binding) != {"target"}:
                raise Error(f"settings.{name} accepts only target")
            from .storage import saved_path
            if not isinstance(binding["target"], str):
                raise Error("Setting target must be a string")
            target = Path(binding["target"]).expanduser()
            if not target.is_absolute():
                raise Error("Setting target must be absolute")
            saved_path(str(target))
        for name, data in settings.items():
            if name not in machine_settings:
                raise Error(f"Setting {name}: missing machine settings.{name}.target")
            if "external" in data and data["external"] not in self.doc.get("external_paths", {}):
                raise Error(f"Setting {name}: missing external path binding")
        bindings = self.doc.get("external_paths", {})
        from .personal_hooks import runtime
        for name, data in declared_hooks.items():
            if 'external' in data and data['external'] not in bindings:
                raise Error(f'Hook {name}: missing external path binding')
            selected_agents = set(data['agents']) & (set(self.agents) or {'codex'})
            if not selected_agents:
                raise Error(f'Hook {name}: no declared agent is bound on this machine')
            for agent in selected_agents:
                runtime(self, data['agents'][agent]['runtime'])
        for name, data in skills.items():
            path = data.get("subdir", ".")
            if path != ".":
                relative(path)
            root = data.get("root", "skills")
            if not isinstance(root, str) or (root not in self.roots and not ("root" not in data and self.agents)):
                raise Error(f"Skill {name}: missing target root {root!r}")
            if data.get("mode", "link") not in ("link", "copy"):
                raise Error(f"Skill {name}: expected link or copy mode")
        for name, data in instructions.items():
            if data.get("mode", "link") not in ("link", "copy"):
                raise Error(f"Instruction {name}: expected link or copy mode")
            field = "repo" if "repo" in data else "external"
            if field == "external" and data[field] not in bindings:
                raise Error(f"Instruction {name}: missing machine external_paths.{data[field]}")
            if data.get("subdir", ".") != ".":
                relative(data["subdir"])
            relative(data.get("entry"))
            for field in (f for f in ("root", "entry_root") if f in data):
                if not isinstance(data.get(field), str) or data[field] not in self.roots:
                    raise Error(f"Instruction {name}: missing target root {field}")
            relative(data.get("destination", name))
            if "entry_destination" in data:
                relative(data["entry_destination"])
            if "entry_root" not in data and not self.agents:
                raise Error(f"Instruction {name}: missing target root entry_root")
        for name, data in directories.items():
            if "external" in data and data["external"] not in bindings:
                raise Error(f"Directory {name}: missing machine external_paths.{data['external']}")
            if data.get("subdir", ".") != ".":
                relative(data["subdir"])
            root = data.get("root")
            if not isinstance(root, str) or root not in self.roots:
                raise Error(f"Directory {name}: missing target root {root!r}")
            relative(data.get("destination", name))
            if data.get("mode", "link") not in ("link", "copy"):
                raise Error(f"Directory {name}: expected link or copy mode")
        external_paths = {identifier(k): absolute(v) for k, v in bindings.items()}
        protected = [self.path, self.state_dir, self.checkout_root]
        if self.catalog_path:
            protected.append(self.catalog_source.path if self.catalog_source else self.catalog_path)
        paths = list(external_paths.values())
        for i, path in enumerate(paths):
            if any(overlaps(path, other) for other in protected + paths[:i]):
                raise Error("External source roots must be disjoint from other sources, checkouts, inventory and state")
        self._external_paths = external_paths
        self._external_names = set(externals)
        self._instructions = instructions
        self._settings = settings
        self._hooks = declared_hooks
        self._directories = directories
        if self.modes.keys() - (skills.keys() | directories.keys() | instructions.keys()):
            raise Error("Machine mode override does not name a skill, directory, or instruction in the catalog")
        from .updates import resolve_policies

        self._update_policies = resolve_policies(document.get("updates", {}), skills)
        self._update_policies.update(resolve_policies(document.get("updates", {}), directories, kind="directories"))
        # Full mode supplies its own opt-in default; explicit empty-trigger
        # overrides still resolve through the same precedence rules.
        from .updates import TRIGGERS
        self._full_update_policies = resolve_policies(document.get('updates', {}), skills, default_trigger=list(TRIGGERS))
        self._full_update_policies.update(resolve_policies(document.get('updates', {}), directories,
                                                          default_trigger=list(TRIGGERS), kind="directories"))
        self._repositories = repositories
        self._catalog = skills
        return skills

    @staticmethod
    def _validate_repository(data, label):
        repository = data.get("repository")
        if not isinstance(repository, str) or not repository or repository.startswith("-"):
            raise Error(f"{label}: repository must be a Git URL or absolute local repository path")
        if not (Path(repository).expanduser().is_absolute() or ":" in repository):
            raise Error(f"{label}: use an absolute path for a local Git repository")
        if "branch" in data and (not isinstance(data["branch"], str) or not data["branch"] or data["branch"].startswith("-")):
            raise Error(f"{label}: branch must be a nonempty branch name")

    def update_policies(self) -> dict:
        """Return validated effective policies from the currently bound catalog."""
        self.catalog()
        return self._update_policies

    def full_update_policies(self):
        self.catalog()
        return getattr(self, '_full_update_policies', {})

    def settings_update_policies(self, *, full=False):
        """Settings own independent schedules; reception always includes apply."""
        self.catalog()
        from .updates import TRIGGERS, policy_fields
        defaults = {"trigger": list(TRIGGERS) if full else "manual",
                    "min_interval": 600, "timeout": 30}
        return {name: {**policy_fields(defaults, "settings update defaults"),
                       **policy_fields(data.get("update", {}), f"settings.{name}.update")}
                for name, data in self._settings.items()}

    def named_source(self, name: str) -> Source | None:
        """Resolve one catalog source root independently of its consumer items."""
        self.catalog()
        if name in self._repositories:
            data = self._repositories[name]
            repository = data['repository']
            if Path(repository).expanduser().is_absolute():
                repository = str(absolute(repository))
            path = self.checkout_root / '.aem-repositories' / name
            if path.resolve() != path:
                raise Error(f"Managed checkout path must not redirect through a symlink: {path}")
            return Source('source:' + name, path, repository, data.get('branch'))
        if name in self._external_names:
            if name not in self._external_paths:
                raise Error(f"Source {name}: missing machine external_paths.{name}")
            return Source('source:' + name, self._external_paths[name], None, None)
        return None

    @property
    def sources(self) -> dict[str, Source]:
        """Derive checkout paths; the inventory never needs device-local bindings."""
        result = {}
        declarations = {**self.catalog(), **self._directories, **self._instructions, **self._settings, **self._hooks}
        for name, data in declarations.items():
            if "external" in data:
                result[name] = Source(name, self._external_paths[data["external"]], None, None)
                continue
            shared = data.get("repo")
            settings = self._repositories[shared] if shared else data
            repository = settings["repository"]
            if Path(repository).expanduser().is_absolute():
                repository = str(absolute(repository))
            path = self.checkout_root / ".aem-repositories" / shared if shared else self.checkout_root / name
            if path.resolve() != path:
                raise Error(f"Managed checkout path must not redirect through a symlink: {path}")
            result[name] = Source(name, path, repository, settings.get("branch"))
        return result

    def instruction_agents(self, data):
        # Explicit destinations remain single-target. Match their binding
        # when possible, rather than interpreting one path as several agents.
        if "entry_root" in data:
            root = self.roots[data["entry_root"]]
            matches = [n for n, p in self.agents.items() if absolute(p["root"]) == root]
            if len(matches) > 1:
                raise Error("Explicit entry_root matches multiple agents")
            if matches:
                return matches
            if len(self.agents) == 1:
                return list(self.agents)
            if not self.agents or "codex" in self.agents:
                return ["codex"]  # Use the built-in profile for an explicit destination.
            raise Error("Explicit entry_root must match one selected agent")
        return sorted(self.agents, key=lambda n: (n != "codex", n))

    def declarations(self, source: Source) -> list[Item]:
        from .agents import profile, suffix
        self.catalog()
        if source.name in self._directories:
            data = self._directories[source.name]
            subdir = data.get("subdir", ".")
            return [Item(source.name, "directory", subdir, source.path / subdir,
                         self.target(data["root"], relative(data.get("destination", source.name))),
                         self.modes.get(source.name, data.get("mode", "link")), "directory",
                         preserve_symlinks=data.get("preserve_symlinks", False))]
        if source.name in self._hooks:
            result = []
            data = self._hooks[source.name]
            for agent in sorted(set(data['agents']) & (set(self.agents) or {'codex'})):
                binding = data['agents'][agent]
                root = f'aem-agent-{agent}' if self.agents else 'agent'
                result.append(Item(source.name, 'hook' + suffix(agent), binding['script'],
                    source.path / relative(binding['script']), self.target(root, relative(profile(agent).hook_name)),
                    'agent-hook', 'personal-hook', agent=agent))
            return result
        if source.name in self._settings:
            from .settings import declaration
            return [declaration(self, source, self._settings[source.name])]
        if source.name in self._instructions:
            data = self._instructions[source.name]
            subdir = data.get("subdir", ".")
            payload = source.path / subdir
            mode = self.modes.get(source.name, data.get("mode", "link"))
            entry_relative = data["entry"] if subdir == "." else subdir + "/" + data["entry"]
            result = []
            for agent in self.instruction_agents(data):
                adapter, tail = profile(agent), suffix(agent)
                destination = data.get("destination", source.name) + (tail if "entry_root" not in data else "")
                target = self.target(data.get("root"), relative(destination))
                root = data.get("entry_root", f"aem-agent-{agent}")
                entry_target = self.target(root, relative(data.get("entry_destination", adapter.entry_name)))
                hook_target = self.target(root, relative(adapter.hook_name))
                result.extend([
                    Item(source.name, "bundle" + tail, subdir, payload, target, mode, "instruction", data["entry"], agent),
                    Item(source.name, "entry" + tail, entry_relative, payload / data["entry"], entry_target,
                         "link", "instruction-entry", data["entry"], agent,
                         link_target=target / data["entry"] if mode == "copy" else None),
                    Item(source.name, "hook" + tail, subdir, payload, hook_target, "agent-hook",
                         "instruction-hook", data["entry"], agent)])
            return result
        data = self.catalog()[source.name]
        relative_path = data.get("subdir", ".")
        payload = source.path if relative_path == "." else source.path / relative(relative_path)
        mode = self.modes.get(source.name, data.get("mode", "link"))
        names = sorted(self.agents, key=lambda n: (n != "codex", n)) if self.agents else ["codex"]
        by_target = {}
        for agent in names:
            profile(agent).validate_skill_name(source.name)
            root = data.get("root", f"aem-skills-{agent}" if self.agents else "skills")
            target = self.target(root, Path(source.name))
            by_target.setdefault(target, []).append(agent)
        return [Item(source.name, source.name + suffix(names[0]), relative_path, payload, target, mode, "skill",
                     agent=names[0], agents=tuple(names)) for target, names in by_target.items()]

    def target(self, root: str | None, destination: Path) -> Path:
        # Instruction bundles default to per-configuration storage, like checkouts.
        base = self.roots[root] if root is not None else (self.path.parent / (self.path.name + ".bundles")).resolve()
        target = base / destination
        # Resolve ancestors but never follow an existing target symlink.
        target = target.parent.resolve() / target.name
        if base not in target.parents:
            raise Error(f"Target escapes its root: {target}")
        if any(target == r for r in self.roots.values()):
            raise Error(f"Cannot own an entire configured target root: {target}")
        protected = [s.path for s in self.sources.values()] + [self.state_dir, self.path]
        if self.catalog_path:
            protected.extend([self.catalog_source.path if self.catalog_source else self.catalog_path, self.checkout_root])
        if any(overlaps(target, path) for path in protected):
            raise Error(f"Target overlaps source, inventory, or manager state: {target}")
        return target
