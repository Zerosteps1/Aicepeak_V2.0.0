"""Control and candidate checkouts, disposable checkouts built from Git objects, and trusted helper calls.

The control checkout is a clean clone on the device's control branch (a listed branch, default the config
branch); trusted CLI code runs only from it or from a pinned export of one of its commits. Rules, branch list
and policy always come from the tip of the config branch. session.py never sees the candidate itself: it gets a
disposable checkout whose files come byte-exact from Git objects (no checkout filters, hooks or attribute
conversions).
"""
from __future__ import annotations

import ast
import collections
import contextlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import tempfile

import branches
import common
from common import Blocked, git, is_ancestor, out, require
import session

ROOT = Path(__file__).resolve().parents[3]
LOCAL_CONFIG = re.compile(r'core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode)'
                          r'|remote\.origin\.(url|fetch)|branch\..+\.(remote|merge|rebase|vscode-merge-base)'
                          r'|user\.(name|email)|pull\.rebase')
Policy = collections.namedtuple('Policy', 'tip config model')  # config branch tip, its config.json, branches.Model


def repository_config(root=None):
    return json.loads(((root or ROOT) / 'factory/config.json').read_text())


def github_url(config):
    return common.GITHUB.format(repository=config['repository'])


def device():
    require(common.CONFIG_FILE.is_file(), 'factory is not installed on this device: run '
            'tools/factory/cli/install-factory-cli.sh (docs/factory-cli.md#install)')
    data = json.loads(common.CONFIG_FILE.read_text())
    require(isinstance(data, dict) and all(isinstance(data.get(key), str) and data[key].startswith('/')
                                           for key in ('control', 'candidate', 'python', 'bin')),
            f'invalid device configuration {common.CONFIG_FILE}; rerun the installer')
    branch = data.get('branch')
    require(branch is None or (isinstance(branch, str) and branches.NAME.fullmatch(branch)),
            f'invalid control branch in {common.CONFIG_FILE}; rerun the installer')
    return {'control': Path(data['control']), 'candidate': Path(data['candidate']),
            'python': data['python'], 'bin': Path(data['bin']), 'branch': branch}


def record_branch(name):
    """The device's control branch in cli.json; callers hold the control lock."""
    data = json.loads(common.CONFIG_FILE.read_text())
    data['branch'] = name
    common.atomic_json(common.CONFIG_FILE, data)


def toplevel(path):
    """The on-disk spelling Git reports; case-insensitive file systems accept other spellings too."""
    return Path(out(path, 'rev-parse', '--show-toplevel'))


def common_dir(path):
    return Path(out(path, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()


def objects_dir(path):
    return Path(out(path, 'rev-parse', '--path-format=absolute', '--git-path', 'objects'))


def _inside(inner, outer):
    return any(os.path.samefile(parent, outer) for parent in [inner, *inner.parents] if parent.exists())


def separate(control, candidate):
    """Control and candidate must be two different repositories, neither inside the other."""
    require(not _inside(candidate, control) and not _inside(control, candidate),
            f'control checkout {control} and candidate checkout {candidate} must be separate folders')
    require(common_dir(control) != common_dir(candidate),
            'control and candidate checkouts share one Git repository; use two separate clones')


def verify_candidate(candidate, config):
    candidate = Path(candidate)
    require(candidate.is_dir() and (candidate / '.git').is_dir() and not (candidate / '.git').is_symlink(),
            f'candidate checkout {candidate} is missing or not a plain clone; rerun the installer')
    keys = out(candidate, 'config', '--local', '--no-includes', '--name-only', '--list').splitlines()
    unknown = sorted({key for key in keys if not LOCAL_CONFIG.fullmatch(key)})
    require(not unknown, f'candidate {candidate}/.git/config has settings factory does not run with: '
            + ', '.join(unknown) + ' (remove them with `git config --local --unset <key>`)')
    session.identity(candidate, config)
    for key in ('user.name', 'user.email'):
        require(out(candidate, 'config', '--local', '--get', key, check=False),
                f'candidate has no local {key}; rerun the installer or run `git -C {candidate} config --local {key} ...`')


def config_at(repo, sha):
    raw = git(repo, 'cat-file', 'blob', f'{sha}:factory/config.json').stdout
    try:
        return json.loads(raw)
    except ValueError:
        raise Blocked(f'factory/config.json at {sha[:12]} is not valid JSON') from None


def remote_tip(repo, name):
    found = git(repo, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{name}^{{commit}}', check=False)
    return found.stdout.decode().strip() if found.returncode == 0 else None


def read_policy(repo, config):
    """The config branch tip last fetched into repo, its configuration and branch model (None before any fetch).
    Branch names, gates, routing and review modes come only from here, never from the code's own copy. The code
    names a config branch; a finished change of it is followed once (branches.follow), so the result may name
    another one: every later use takes model.config_branch, never config['config_branch']."""
    name, tips = config['config_branch'], {}
    if not remote_tip(repo, name):
        return None

    def read(branch):
        tips[branch] = remote_tip(repo, branch)
        data = config_at(repo, tips[branch]) if tips[branch] else None
        require(not isinstance(data, dict) or data.get('repository') == config['repository'],
                f'factory/config.json on {branch} names another repository')
        return data
    followed, data = branches.follow(read, name)
    return Policy(tips[followed], data, branches.parse(data))


def fetch_policy(repo, config, *more):
    """Fetch the config branch the code names (and more); when its configuration names another config branch, that
    one too, so read_policy can follow a finished change. Returns the fetched tips."""
    name = config['config_branch']
    tips = fetch(repo, config, name, *more)
    require(name in tips, f'the config branch {name} is not on GitHub; factory reads every rule from it and stops without it')
    data = config_at(repo, tips[name])
    target = data.get('config_branch') if isinstance(data, dict) else None
    if isinstance(target, str) and target != name and branches.NAME.fullmatch(target) and target not in tips:
        tips.update(fetch(repo, config, target))
    return tips


def unlisted(branch, name):
    return (f'the control checkout follows {branch}, which factory/config.json on {name} does not list (any more); '
            f'switch back with `factory use branch {name}`')


def update_control(control, config, *, branch=None, online=True, listed=True):
    """Verify the control checkout and fast-forward it to origin/<branch>, the device's control branch (default: the
    config branch the code names). Also fetches the config branch, whose tip is the policy, following a finished
    change of it. With listed=False (`factory use branch`) a control branch that is unlisted or missing on GitHub is
    only verified, so the device can always switch away; so is a clean control checkout on another listed branch, as
    an interrupted `factory use branch` leaves it. Never deletes or resets files."""
    control = Path(control)
    branch = branch or config['config_branch']
    try:
        sha = session.identity(control, config)
        session.clean_tree(control, sha)
    except Blocked as exc:
        raise Blocked(f'control checkout {control}: {exc}. Never edit it; remove or revert the named '
                      'file yourself (factory never deletes files there), then retry') from None
    current = out(control, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False)
    where = f'control checkout {control} is on {current or "a detached HEAD"}'
    require(current == branch or not listed, f'{where}, but it must stay on {branch}, its recorded control branch: '
            '`factory use branch <listed branch>` switches it')
    if current != branch:  # e.g. an interrupted `factory use branch`: switched, not yet recorded; `use` finishes it
        tips = fetch_policy(control, config, branch, *([current] if current else [])) if online else {}
        policy = read_policy(control, config)
        require(policy and current in policy.model.names, f'{where}, neither its recorded control branch {branch} nor '
                f'a listed branch: switch it back yourself (`git -C {control} switch {branch}`), then retry')
        # Its code runs `use` next, so it must be a commit GitHub has on that branch, never an own commit.
        require(current not in tips or is_ancestor(control, sha, tips[current]),
                f'{where} with own commits; it must never carry any. Recreate it with the installer')
        return sha, False
    if not online:
        return sha, False
    tips = fetch_policy(control, config, branch)
    model = read_policy(control, config).model
    name = model.config_branch
    if branch not in model.names:
        require(not listed, unlisted(branch, name))
        return sha, False
    if branch not in tips and not listed:
        return sha, False
    require(branch in tips, f'{branch} is not on GitHub; switch with `factory use branch {name}`')
    remote = tips[branch]
    if remote == sha:
        return sha, False
    require(is_ancestor(control, sha, remote), f'control checkout {control} cannot fast-forward to origin/{branch}; '
            'it must never carry own commits. Recreate it with the installer')
    git(control, 'merge', '--ff-only', '--quiet', remote)
    session.clean_tree(control, remote)
    return remote, True


def fetch(repo, config, *branches):
    """Fetch named branches from GitHub over https into refs/remotes/origin/*; missing branches are skipped."""
    url, branches = github_url(config), list(dict.fromkeys(branches))
    present = set()
    listing = out(repo, 'ls-remote', '--heads', url, *[f'refs/heads/{name}' for name in branches], network=True)
    for line in listing.splitlines():
        present.add(line.split('\t', 1)[1][len('refs/heads/'):])
    refspecs = [f'+refs/heads/{name}:refs/remotes/origin/{name}' for name in branches if name in present]
    if refspecs:
        git(repo, 'fetch', '--quiet', '--no-tags', url, *refspecs, network=True)
    return {name: out(repo, 'rev-parse', f'refs/remotes/origin/{name}') for name in branches if name in present}


def tree_files(repo, sha):
    entries = []
    for record in git(repo, 'ls-tree', '-rz', '--full-tree', sha).stdout.split(b'\0'):
        if not record:
            continue
        info, raw = record.split(b'\t', 1)
        mode, kind, oid = info.decode().split()
        name = raw.decode('utf-8')
        common.safe_path(name)
        require(kind == 'blob' and mode in ('100644', '100755'), f'symlinks and submodules are unsupported: {name}')
        entries.append((name, mode, oid))
    return entries


def export_tree(repo, sha, dest):
    """Write every file of a commit byte-exact from Git objects: no filters, hooks or checkout."""
    dest = Path(dest)
    entries = tree_files(repo, sha)
    process = subprocess.Popen([common.tool('git'), '--no-pager', '--no-replace-objects', '-C', str(repo), *common.GIT_SAFETY,
                                'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               env={'PATH': common.search_path(), 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                                    'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': ''})
    common.feed(process.stdin, b''.join(oid.encode() + b'\n' for _, _, oid in entries))
    try:
        for name, mode, oid in entries:
            header = process.stdout.readline().split()
            require(len(header) == 3 and header[0].decode() == oid and header[1] == b'blob', f'object read failed: {name}')
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if mode == '100755' else 0o644)
    finally:
        process.stdout.close()
        process.wait(timeout=60)
    require(process.returncode == 0, 'reading Git objects failed')
    return dest


def materialize(dest, sha, *, objects, origin, branch=None):
    """A disposable clean checkout of sha that session.py accepts (identity, clean_tree, branch)."""
    dest = Path(dest)
    dest.mkdir(mode=0o700, exist_ok=True)
    require(not any(dest.iterdir()), f'disposable checkout {dest} is not empty')
    git(dest, 'init', '--quiet')
    (dest / '.git/objects/info/alternates').write_text(''.join(f'{path}\n' for path in objects))
    git(dest, 'config', 'remote.origin.url', origin)
    if branch:
        git(dest, 'update-ref', f'refs/heads/{branch}', sha)
        git(dest, 'symbolic-ref', 'HEAD', f'refs/heads/{branch}')
    else:
        git(dest, 'update-ref', '--no-deref', 'HEAD', sha)
    export_tree(dest, sha, dest)
    git(dest, 'read-tree', sha)
    git(dest, 'update-index', '-q', '--refresh')  # stat data for `apply --index`; no filters exist here
    return dest


@contextlib.contextmanager
def scratch(prefix):
    root = common.STATE_DIR / 'tmp'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def policy_checkout(control, sha, config):
    """Trusted tools and rules at exactly a verified config branch tip, independent of later control updates."""
    with scratch('policy-') as path:
        yield materialize(path / 'checkout', sha, objects=[objects_dir(control)], origin=github_url(config))


@contextlib.contextmanager
def candidate_snapshot(candidate, control, sha, branch, config):
    """The committed candidate state as session.py's --candidate: clean, on the pushed branch name."""
    with scratch('candidate-') as path:
        yield materialize(path / 'checkout', sha, objects=[objects_dir(candidate), objects_dir(control)],
                          origin=github_url(config), branch=branch)


def tool_command(checkout, script, *args):
    # -E -S keep PYTHON* variables and site customisations out; the script directory stays importable.
    return [sys.executable, '-E', '-S', '-B', str(Path(checkout) / 'tools/factory' / script), *map(str, args)]


def tool_env():
    return common.child_env('CODEX_ACCESS_TOKEN', 'FACTORY_PUBLISHER_APP_PRIVATE_KEY')


def run_tool(checkout, script, *args, capture=False, timeout=None):
    """Run a trusted factory script from a checkout. Interactive by default; captured output is parsed by callers."""
    command = tool_command(checkout, script, *args)
    process = subprocess.Popen(command, cwd=checkout, env=tool_env(), text=True,
                               stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except KeyboardInterrupt:
        settle(process)
        raise
    return process.returncode, stdout or '', stderr or ''


def settle(process, grace=30):
    """Ctrl-C reached the child too: give session.py time to stop its reviewer before anything is killed."""
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def last_json(text):
    """session.py prints JSON results; a non-passing preflight still prints JSON with exit code 1."""
    text = text.strip()
    for start in [i for i, char in enumerate(text) if char == '{' and (i == 0 or text[i - 1] == '\n')]:
        try:
            return json.loads(text[start:])
        except ValueError:
            continue
    return None


def blocked_reason(stderr):
    lines = [line for line in stderr.splitlines() if line.startswith(('BLOCKED:', 'STOPPED:'))]
    return common.printable(lines[-1] if lines else stderr.strip()[-500:], 600)


def github():
    return session.HumanGitHub()


def maintainer(gh, config):
    """The gh login must be a configured maintainer with write access (session.authorize)."""
    return session.authorize(gh, config)


def head(repo):
    return out(repo, 'rev-parse', '--verify', 'HEAD^{commit}')


def current_branch(repo):
    return out(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False)


def direct_imports(repo, base, sha):
    """Unchanged repository modules that changed Python files import directly (preflight --context)."""
    changed = [path for path in out(repo, 'diff', '--name-only', '--no-renames', '-z', base, sha).split('\0') if path]
    files = set(out(repo, 'ls-tree', '-r', '--name-only', '-z', sha).split('\0'))
    found = set()
    for path in [p for p in changed if p.endswith('.py') and p in files]:
        try:
            syntax = ast.parse(git(repo, 'show', f'{sha}:{path}').stdout)
        except SyntaxError:
            continue
        parent = PurePosixPath(path).parent
        for node in ast.walk(syntax):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else
                       [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                for root in (parent, *parent.parents):
                    stem = (root / module.replace('.', '/')).as_posix()
                    for candidate in (stem + '.py', stem + '/__init__.py'):
                        if candidate in files and candidate not in changed:
                            found.add(candidate)
    return sorted(found)[:30]
