#!/usr/bin/env python3
"""Verify that installed releases self-update to a candidate revision and keep their state.

Each baseline release is installed from its tag through its own repository installer,
in a disposable user profile. The candidate revision is published to a temporary local
release repository under a synthetic version that orders directly after it, then
installed through the baseline's own `aem self update` worker.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_profile import IsolatedProfile, require  # noqa: E402


VERSION = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
RELEASE = re.compile(r'(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d*))?')
TAG = re.compile(r'v(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d*)|-(alpha|beta|rc)(?:\.(\d+))?)?')
LABELS = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1, 'rc': 2, None: 3}


def next_release(version):
    """Return a release version that orders directly after `version`."""
    match = RELEASE.fullmatch(version)
    require(match, f'Unsupported candidate version: {version}')
    major, minor, patch, label, number = match.groups()
    if label:
        return f'{major}.{minor}.{patch}{label}{int(number or 0) + 1}'
    return f'{major}.{minor}.{int(patch) + 1}'


def tag_order(tag):
    """Order supported release tags as AEM self-update does, or return None."""
    match = TAG.fullmatch(tag)
    if not match:
        return None
    major, minor, patch, label, number, semver_label, semver_number = match.groups()
    return (int(major), int(minor), int(patch), LABELS[label or semver_label],
            int(number or semver_number or 0))


def default_baselines(tags):
    """Select the newest final release and the newest release of any kind."""
    releases = sorted((order, tag) for tag in tags if (order := tag_order(tag)) is not None)
    finals = [tag for order, tag in releases if order[3] == LABELS[None]]
    return list(dict.fromkeys([*finals[-1:], *(tag for _, tag in releases[-1:])]))


def differences(left, right, path='$'):
    """List JSON paths whose values differ between two documents."""
    if isinstance(left, dict) and isinstance(right, dict):
        return [found for key in sorted(left.keys() | right.keys())
                for found in differences(left.get(key), right.get(key), f'{path}.{key}')]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [found for index, pair in enumerate(zip(left, right))
                for found in differences(*pair, f'{path}[{index}]')]
    return [] if left == right else [f'{path}: {left!r} -> {right!r}']


def digest_tree(root):
    """Map each file and link below `root` to its content or link target."""
    result = {}
    if not os.path.lexists(root):
        return result
    for path in sorted([root, *root.rglob('*')]):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = 'link:' + os.readlink(path)
        elif path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def publish_candidate(profile, checkout, candidate):
    """Publish `candidate` under the next version in a local release repository."""
    release = profile.root / 'release.git'
    profile.git(profile.root, 'init', '--quiet', '--bare', '-b', 'master', release)
    prepared = profile.root / 'candidate'
    profile.git(profile.root, 'clone', '--quiet', '--no-local', '--no-checkout', checkout, prepared)
    profile.git(prepared, 'checkout', '--quiet', '--detach', candidate)
    pyproject = prepared / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8')
    current = VERSION.search(text)
    require(current, 'Candidate pyproject.toml has no project version')
    version = next_release(current.group(1))
    pyproject.write_text(VERSION.sub(f'version = "{version}"', text, count=1), encoding='utf-8')
    profile.git(prepared, 'commit', '--quiet', '-am', f'Release {version} for upgrade verification')
    revision = profile.git(prepared, 'rev-parse', 'HEAD').strip()
    profile.git(prepared, 'tag', 'v' + version)
    profile.git(prepared, 'push', '--quiet', release, 'HEAD:refs/heads/master', 'v' + version)
    return release, version, revision


def create_state(profile):
    """Install copied, linked, and settings content with local edits to preserve."""
    source = profile.root / 'content'
    for name in ('smoke', 'linked'):
        (source / name).mkdir(parents=True)
        (source / name / 'SKILL.md').write_text(
            f'---\nname: {name}\ndescription: Upgrade verification\n---\n\nSkill body.\n', encoding='utf-8')
    (source / 'settings.toml').write_text('count = 1\n', encoding='utf-8')
    profile.git(source, 'init', '--quiet', '-b', 'main')
    profile.git(source, 'add', '.')
    profile.git(source, 'commit', '--quiet', '-m', 'Upgrade fixture')
    catalog = profile.root / 'catalog.toml'
    catalog.write_text(
        'version = 2\n[sources.fixture]\ntype = "git"\n'
        f'repository = {json.dumps(str(source), ensure_ascii=False)}\n'
        '[skills.smoke]\nsource = "fixture"\nsubdir = "smoke"\n[skills.smoke.install]\nmode = "copy"\n'
        '[skills.linked]\nsource = "fixture"\nsubdir = "linked"\n[skills.linked.install]\nmode = "link"\n'
        '[settings.local]\nsource = "fixture"\npath = "settings.toml"\nformat = "toml"\n', encoding='utf-8')
    settings = profile.root / 'settings.toml'
    settings.write_text('# preserved comment\ncount = 1\nprivate = "local"\n', encoding='utf-8')
    # Catalog skills share the Codex skill root with the official skill link.
    profile.aem('bootstrap', catalog, '--checkout-root', profile.root / 'checkouts',
                '--setting-target', f'local={settings}')
    profile.aem('apply')
    skills = profile.agent_skills('codex')
    (skills / 'smoke/local.md').write_text('Local edit\n', encoding='utf-8')
    return source, skills, settings


def wait_for_update(profile, token, timeout):
    """Wait for the worker's recorded result for `token`."""
    # Polling through the CLI would take the configuration lock that the
    # worker's official-skill continuation needs, so watch the result file.
    result = Path(str(profile.machine) + '.state') / 'self-update.json'
    deadline = time.monotonic() + timeout
    while True:
        try:
            attempt = json.loads(result.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            attempt = {}
        if attempt.get('token') == token and attempt.get('finished'):
            return json.loads(profile.aem('self', 'status'))['last_attempt']
        require(time.monotonic() < deadline, f'Self-update did not finish within {timeout} seconds: {attempt}')
        time.sleep(2)


def verify(checkout, baseline, candidate, timeout):
    with tempfile.TemporaryDirectory(prefix='aem-upgrade-') as directory:
        profile = IsolatedProfile(directory)
        bashrc = profile.home / '.bashrc'
        bashrc.write_text('# preserved shell line\n', encoding='utf-8')
        release, version, revision = publish_candidate(profile, checkout, candidate)

        installed = profile.root / 'baseline'
        profile.git(profile.root, 'clone', '--quiet', '--no-local', '--no-checkout', checkout, installed)
        profile.git(installed, 'checkout', '--quiet', '--detach', baseline)
        baseline_version = VERSION.search((installed / 'pyproject.toml').read_text(encoding='utf-8')).group(1)
        profile.install(installed, '--shell', 'bash', '--agent', 'codex', '--agent', 'claude',
                        '--automation', 'policies', '--self-update', 'breaking', '--update-repository', release)
        status = json.loads(profile.aem('self', 'status'))
        require(status['version'] == baseline_version,
                f'Baseline installation reports {status["version"]}, expected {baseline_version}')

        source, skills, settings = create_state(profile)
        agents = {'codex': profile.home / '.codex', 'claude': profile.home / '.claude'}
        skills_before = digest_tree(skills)
        agents_before = {name: digest_tree(path) for name, path in agents.items()}
        settings_before = settings.read_bytes()
        status_before = json.loads(profile.aem('status'))

        queued = json.loads(profile.aem('self', 'update', '--mode', 'breaking'))
        require(queued.get('status') == 'queued', f'Self-update was not queued: {queued}')
        attempt = wait_for_update(profile, queued['token'], timeout)
        require(attempt['status'] == 'updated', f'Self-update did not install the candidate: {attempt}')
        require(attempt.get('version') == version and attempt.get('revision') == revision,
                f'Self-update installed {attempt.get("version")} at {attempt.get("revision")}, '
                f'expected {version} at {revision}')
        require(json.loads(profile.aem('self', 'status'))['version'] == version,
                'Updated installation reports another version')

        # The candidate reads the baseline's state without changing installed contents.
        require(digest_tree(skills) == skills_before, 'Self-update changed managed skill contents')
        require(settings.read_bytes() == settings_before, 'Self-update changed managed settings')
        require(bashrc.read_text(encoding='utf-8').startswith('# preserved shell line\n'),
                'Self-update lost the existing shell profile content')
        # The self-update block records this attempt; everything else must match.
        changed = differences({**status_before, 'self_update': None},
                              {**json.loads(profile.aem('status')), 'self_update': None})
        require(not changed, 'Candidate status differs from baseline status:\n' + '\n'.join(changed))
        # The local edit keeps its copy protected; other items reapply unchanged.
        profile.aem('apply', '--item', 'smoke', code=1)
        profile.aem('apply', '--item', 'linked', '--item', 'local')
        require(digest_tree(skills) == skills_before and settings.read_bytes() == settings_before,
                'Candidate apply changed contents installed by the baseline')

        # The candidate continues ordinary delivery on the inherited state.
        (source / 'settings.toml').write_text('count = 2\n', encoding='utf-8')
        profile.git(source, 'commit', '--quiet', '-am', 'Update settings fixture')
        profile.aem('update', 'local')
        profile.aem('apply', '--item', 'local')
        text = settings.read_text(encoding='utf-8')
        require('count = 2' in text and 'private = "local"' in text,
                'Candidate did not apply a received settings update safely')
        # Setup on the updated installation keeps the baseline's agent integrations.
        profile.aem('setup', '--agent', 'codex', '--agent', 'claude')
        changed = sorted(f'{name}/{path}' for name, root in agents.items()
                         for path, value in digest_tree(root).items() if agents_before[name].get(path) != value)
        require(not changed, 'Candidate setup rewrote agent profile files: ' + ', '.join(changed))
        print(f'Verified self-update from {baseline} ({baseline_version}) to {candidate} as {version}', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--baseline', action='append',
                        help='installed release tag (repeatable; default: newest final and newest release '
                             'tags merged into the candidate)')
    parser.add_argument('--candidate', default='HEAD', help='revision to publish as the next release')
    parser.add_argument('--checkout', type=Path, default=Path(__file__).resolve().parents[1],
                        help='Git checkout containing both revisions (default: this repository)')
    parser.add_argument('--timeout', type=float, default=600, help='seconds to wait for each update worker')
    options = parser.parse_args(argv)
    try:
        for tool in ('git', 'uv'):
            require(shutil.which(tool), f'{tool} must be available on PATH')
        checkout = options.checkout.resolve()
        baselines = options.baseline
        if not baselines:
            tags = subprocess.run(['git', '-C', str(checkout), 'tag', '--merged', options.candidate],
                                  check=True, capture_output=True, text=True).stdout.split()
            baselines = default_baselines(tags)
            require(baselines, f'No release tags are merged into {options.candidate}')
        for baseline in baselines:
            verify(checkout, baseline, options.candidate, options.timeout)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(f'Upgrade verification: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
