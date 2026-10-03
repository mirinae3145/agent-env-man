#!/usr/bin/env python3
"""Verify an installed wheel without development dependencies or live integrations."""

import argparse
from importlib import metadata, util
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import tomllib


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_captured(*arguments, **options):
    """Run verification children without opening Windows console windows."""
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(*arguments, **options)


def verify_settings(cli, root, source, git):
    """Exercise both installed format adapters and preserve actual-file edits."""
    for format in ("toml", "json"):
        name = "settings_" + format
        payload = source / (name + "." + format)
        target = root / (name + "." + format)
        parse = tomllib.loads if format == "toml" else json.loads

        def document(count, *, local=False):
            if format == "toml":
                return f'# preserved comment\ncount = {count}\n' + ('private = "local"\n' if local else '')
            return f'{{"count": {count}' + (', "private": "local"' if local else '') + '}\n'

        target.write_text(document(1, local=True), encoding="utf-8")
        cli("apply", "--item", name)
        before = target.read_bytes()
        cli("apply", "--item", name)
        require(target.read_bytes() == before, f"{format}: unchanged apply rewrote the target")
        stage = Path(json.loads(cli("locate", name))["entry"])
        payload.write_text(document(2), encoding="utf-8")
        git("add", payload.name)
        git("-c", "user.name=AEM runtime check", "-c", "user.email=runtime@example.invalid",
            "commit", "-m", "Update settings fixture")
        cli("update", name)
        require(parse(stage.read_text(encoding="utf-8"))["count"] == 2, f"{format}: update did not receive settings")
        require(parse(target.read_text(encoding="utf-8"))["count"] == 1, f"{format}: update applied settings implicitly")
        cli("apply", "--item", name)
        require(parse(target.read_text(encoding="utf-8")) == {"count": 2, "private": "local"},
                f"{format}: received stage did not apply safely")
        stage.write_text(document(3), encoding="utf-8")
        cli("apply", "--item", name)
        require(parse(target.read_text(encoding="utf-8")) == {"count": 3, "private": "local"},
                f"{format}: stage apply failed or lost unmanaged fields")
        if format == "toml":
            require("# preserved comment" in target.read_text(encoding="utf-8"), "TOML apply lost a local comment")
        cli("export", name)
        checkout_payload = Path(json.loads(cli("locate", name, "--source"))["entry"])
        require(parse(checkout_payload.read_text(encoding="utf-8"))["count"] == 3,
                f"{format}: export did not write staged values")
        require("private" not in parse(checkout_payload.read_text(encoding="utf-8")),
                f"{format}: export implicitly collected unmanaged fields")
        cli("publish", name, "-m", "Publish settings fixture")
        require(parse(payload.read_text(encoding="utf-8"))["count"] == 3,
                f"{format}: local Git publication did not deliver staged values")

        target.write_text(document(4, local=True), encoding="utf-8")
        stage.write_text(document(5), encoding="utf-8")
        before = target.read_bytes()
        cli("apply", "--item", name, code=1)
        require(target.read_bytes() == before, f"{format}: conflict overwrote a local field edit")
        cli("detach", name)
        require(target.read_bytes() == before, f"{format}: detach changed actual settings")
        require(json.loads(cli("locate", name))["detached"], f"{format}: detach retained ownership")


def verify_directories(cli, root, source, git):
    """Verify entry-free directory copies through the installed command flow."""
    target = root / 'personal/agent-loop'
    cli('apply', '--item', 'cases', '--agent', 'claude')
    require((target / 'first.md').read_text(encoding='utf-8') == 'First case\n',
            'Directory apply did not install its payload')
    location = json.loads(cli('locate', 'cases', '--agent', 'claude'))
    require(location['entry'] == str(target), 'Directory locate requires an entry file or agent binding')
    (source / 'cases/first.md').write_text('Received case\n', encoding='utf-8')
    git('add', 'cases')
    git('commit', '-m', 'Update directory fixture')
    cli('update', 'cases')
    require((target / 'first.md').read_text(encoding='utf-8') == 'First case\n',
            'Directory update applied a copy implicitly')
    cli('apply', '--item', 'cases')
    require((target / 'first.md').read_text(encoding='utf-8') == 'Received case\n',
            'Directory apply did not refresh its copy')
    (target / 'local.md').write_text('Preserve local case', encoding='utf-8')
    cli('apply', '--item', 'cases', code=1)
    original = Path(json.loads(cli('locate', 'cases', '--source'))['root'])
    require(not (original / 'local.md').exists(), 'Directory copy edits were implicitly collected')
    cli('detach', 'cases', '--agent', 'claude')
    require((target / 'local.md').read_text(encoding='utf-8') == 'Preserve local case',
            'Directory detach lost local edits')
    require(json.loads(cli('locate', 'cases'))['detached'], 'Directory detach retained ownership')


def verify():
    """Check runtime isolation and local operations in the target interpreter.

    All operation paths and user-profile locations are temporary.
    This checks wheel behavior, not native platform readiness or remote delivery.
    """
    for module in ("coverage", "setuptools"):
        require(util.find_spec(module) is None, f"Runtime environment contains development dependency: {module}")
    import agent_env_man
    package = Path(agent_env_man.__file__).resolve()
    require(Path(sys.prefix).resolve() in package.parents, "AEM must be installed inside the target environment")
    distribution = metadata.distribution("agent-env-man")
    origin = json.loads(distribution.read_text("direct_url.json") or "{}")
    require(not origin.get("dir_info", {}).get("editable"), "Use an installed wheel, not an editable checkout")

    with tempfile.TemporaryDirectory(prefix="aem-runtime-") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        markers = {home / ".bashrc": b"preserve bash\n", home / ".zshrc": b"preserve zsh\n"}
        for path, content in markers.items():
            path.write_bytes(content)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(HOME=str(home), USERPROFILE=str(home),
                           XDG_CONFIG_HOME=str(home / ".config"), CODEX_HOME=str(home / ".codex"),
                           APPDATA=str(home / "AppData/Roaming"), LOCALAPPDATA=str(home / "AppData/Local"),
                           GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_ALLOW_PROTOCOL="file", GIT_TEMPLATE_DIR="",
                           GIT_AUTHOR_NAME="AEM runtime check", GIT_AUTHOR_EMAIL="runtime@example.invalid",
                           GIT_COMMITTER_NAME="AEM runtime check", GIT_COMMITTER_EMAIL="runtime@example.invalid")
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        config = root / "machine.toml"

        def cli(*arguments, code=0, selected_config=config):
            # -I ignores ambient PYTHONPATH and user-site packages; cwd is
            # outside the checkout so imports must come from the wheel.
            result = run_captured([sys.executable, "-I", "-m", "agent_env_man", "--json",
                                     "--config", str(selected_config), *map(str, arguments)],
                                    cwd=root, env=environment, capture_output=True, text=True, timeout=30)
            require(result.returncode == code,
                    f"{arguments}: expected exit {code}, got {result.returncode}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        invalid = root / "invalid.toml"
        invalid.write_text("invalid TOML [", encoding="utf-8")
        executable = Path(sysconfig.get_path("scripts")) / ("aem.exe" if os.name == "nt" else "aem")
        require(executable.is_file(), "Installed aem console entrypoint is missing")
        help_result = run_captured([str(executable), "--config", str(invalid), "--help"],
                                     cwd=root, env=environment, capture_output=True, text=True, timeout=30)
        require(help_result.returncode == 0 and "Usage:" in help_result.stdout,
                f"Installed console help failed: {help_result.stderr}")
        require("Usage:" in cli("--help", selected_config=invalid), "CLI help is unavailable")
        docs = json.loads(cli("docs", selected_config=invalid))
        docs_root = Path(docs["root"])
        require(package.parent in docs_root.parents, "Documentation must come from the installed wheel")
        for resource in ("README.md", "LICENSE.txt", "docs/commands.md", "examples/skills.toml",
                         "docs/personal-hooks.md", "examples/personal-hooks.toml", "examples/directories.toml"):
            require((docs_root / resource).is_file(), f"Missing installed resource: {resource}")
        require(not Path(str(invalid) + ".state").exists(), "Help/docs touched invalid configuration state")

        source = root / "repository"
        source.mkdir()
        skill = b"---\nname: smoke\ndescription: Local runtime verification\n---\n\nTest content.\n"
        (source / "SKILL.md").write_bytes(skill)
        (source / 'cases').mkdir()
        (source / 'cases/first.md').write_text('First case\n', encoding='utf-8')
        for format in ("toml", "json"):
            (source / f"settings_{format}.{format}").write_text(
                'count = 1\n' if format == "toml" else '{"count": 1}\n', encoding="utf-8")

        def git(*arguments):
            return run_captured(["git", "-C", str(source), "-c", f"core.hooksPath={os.devnull}", *arguments],
                                cwd=root, env=environment, check=True, capture_output=True, text=True, timeout=30)

        for arguments in (("init", "-b", "main"), ("add", "SKILL.md", "cases", "settings_toml.toml", "settings_json.json"),
                          ("-c", "user.name=AEM runtime check", "-c", "user.email=runtime@example.invalid",
                           "commit", "-m", "Local fixture")):
            git(*arguments)
        # The local fixture accepts publication into its checked-out branch;
        # no real remote or user Git configuration is involved.
        git("config", "receive.denyCurrentBranch", "updateInstead")
        catalog = root / "catalog.toml"
        catalog.write_text('version = 2\n[sources.fixture]\ntype = "git"\n'
                           f'repository = {json.dumps(str(source), ensure_ascii=False)}\n'
                           '[skills.smoke]\nsource = "fixture"\n[skills.smoke.install]\nmode = "copy"\n'
                           '[directories.cases]\nsource = "fixture"\nsubdir = "cases"\n'
                           '[directories.cases.install]\nroot = "personal"\ndestination = "agent-loop"\nmode = "copy"\n'
                           '[settings.settings_toml]\nsource = "fixture"\npath = "settings_toml.toml"\nformat = "toml"\n'
                           '[settings.settings_json]\nsource = "fixture"\npath = "settings_json.json"\nformat = "json"\n',
                           encoding="utf-8")
        destination = root / "skills"
        cli("bootstrap", catalog, "--checkout-root", root / "checkouts",
            "--root", f"skills={destination}", "--root", f"agent={home / '.codex'}",
            "--root", f"personal={root / 'personal'}",
            "--setting-target", f"settings_toml={root / 'settings_toml.toml'}",
            "--setting-target", f"settings_json={root / 'settings_json.json'}")
        target = destination / "smoke"
        require(not target.exists(), "Bootstrap installed content before apply")
        cli("apply", "--item", "smoke")
        require((target / "SKILL.md").read_bytes() == skill, "Apply did not install the selected payload")
        json.loads(cli("status"))
        (target / "local.txt").write_bytes(b"preserve local edit")
        cli("apply", "--item", "smoke", code=1)
        require((target / "local.txt").read_bytes() == b"preserve local edit", "Apply lost local edits")
        cli("detach", "smoke")
        require((target / "local.txt").read_bytes() == b"preserve local edit", "Detach lost local edits")
        state = json.loads((Path(str(config) + ".state") / "state.json").read_text(encoding="utf-8"))
        require(state["items"]["smoke"].get("detached"), "Detach did not release ownership")
        verify_settings(cli, root, source, git)
        verify_directories(cli, root, source, git)
        # A separate hook target exercises the installed CLI without using any
        # real product home or executing the script.
        hook_source = root / 'hook-source'
        hook_source.mkdir()
        (hook_source / 'observe.py').write_text('raise AssertionError("must not execute")\n', encoding='utf-8')
        hook_catalog = root / 'hook-catalog.toml'
        hook_catalog.write_text('version = 2\n[sources.scripts]\ntype = "external"\n'
            '[hooks.observer]\nsource = "scripts"\n[hooks.observer.agents.codex]\n'
            'event = "SessionEnd"\nruntime = "python"\nscript = "observe.py"\ntimeout = 3\n', encoding='utf-8')
        hook_machine = root / 'hooks-machine.toml'
        hook_target = root / 'hook-target/hooks.json'
        cli('bootstrap', hook_catalog, '--external', f'scripts={hook_source}',
            '--runtime', f'python={sys.executable}', '--root', f'agent={hook_target.parent}',
            selected_config=hook_machine)
        cli('apply', selected_config=hook_machine)
        cli('apply', '--item', 'observer', '--dry-run', selected_config=hook_machine)
        require(not hook_target.exists(), 'Personal registration happened implicitly or during preview')
        cli('apply', '--item', 'observer', selected_config=hook_machine)
        require(len(json.loads(hook_target.read_text())['hooks']['SessionEnd']) == 1,
                'Installed wheel did not register selected personal hook')
        machine = tomllib.loads(hook_machine.read_text(encoding='utf-8'))
        require(machine['runtimes']['python'] == sys.executable,
                'Bootstrap resolved the bound runtime out of its environment')
        if os.name != 'nt':
            # Execute only this explicit probe, after registration; a venv's
            # symlinked interpreter must retain its own environment.
            (hook_source / 'observe.py').write_text(
                'import json,sys\nprint(json.dumps({"prefix":sys.prefix,"executable":sys.executable}))\n',
                encoding='utf-8')
            command = json.loads(hook_target.read_text())['hooks']['SessionEnd'][0]['hooks'][0]['command']
            result = run_captured(command, shell=True, cwd=root, env=environment,
                                  capture_output=True, text=True, check=True, timeout=30)
            require(json.loads(result.stdout) == {'prefix': sys.prefix, 'executable': sys.executable},
                    'Registered hook escaped its bound virtualenv')
        before = hook_target.read_bytes()
        cli('apply', '--item', 'observer', selected_config=hook_machine)
        require(hook_target.read_bytes() == before, 'Personal hook reapply was not idempotent')
        hook_catalog.unlink()
        cli('hooks', 'remove', 'observer', selected_config=hook_machine)
        require(json.loads(hook_target.read_text())['hooks']['SessionEnd'] == [],
                'Installed saved removal required the catalog')
        for path, content in markers.items():
            require(path.read_bytes() == content, "Runtime verification changed a shell profile")
        require(not (home / ".codex/hooks.json").exists(), "Runtime verification registered agent hooks")
    print(f"Verified agent-env-man {distribution.version}: installed runtime without development dependencies")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="Python in a clean environment with the wheel installed")
    options = parser.parse_args(argv)
    try:
        # Venv Python may be a symlink to the base interpreter: resolving it
        # would discard the environment whose installation we need to check.
        interpreter = options.python.expanduser().absolute()
        require(interpreter.is_file(), f"Runtime Python is missing: {interpreter}")
        # Keep the verification body in this file so the target only needs
        # the installed runtime and the standard library, not test helpers.
        command = [str(interpreter), "-I", "-c",
                   "import runpy; runpy.run_path(__import__('sys').argv[1])['verify']()", str(Path(__file__).resolve())]
        result = run_captured(command, capture_output=True, text=True, timeout=180)
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode:
            print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Runtime verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
