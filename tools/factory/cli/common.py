"""Shared plumbing of the factory CLI: device paths, hardened Git, child processes, locks and safe output.

Nothing here runs candidate code. Git always runs without hooks, fsmonitor, global or system configuration,
and only reaches GitHub over https with the maintainer's own gh credential helper.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import tempfile
import threading
import time
import unicodedata

from contracts import Blocked, require, safe_path

CONFIG_FILE = Path.home() / '.config/aicepeak-factory/cli.json'
STATE_DIR = Path.home() / '.local/state/aicepeak-factory'
PINNED_CODEX = Path.home() / '.local/share/aicepeak-factory-cli/node_modules/.bin'
GITHUB = 'https://github.com/{repository}.git'
NETWORK_PROTOCOLS = 'https'
LOCK_WAIT = 60
AUTHOR_KEYS = {'ANTHROPIC_API_KEY': 'aicepeak-factory-anthropic-api-key', 'CONTEXT7_API_KEY': 'aicepeak-factory-context7-api-key'}
GIT_SAFETY = ('-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'core.attributesFile=/dev/null',
              '-c', 'submodule.recurse=false', '-c', 'core.alternateRefsCommand=true')


def printable(text, limit=4000):
    """Untrusted text (model output, GitHub content) must not drive the terminal."""
    text = str(text)
    shown = ''.join(c if c in '\n\t' or unicodedata.category(c) not in ('Cc', 'Cf') else f'\\u{ord(c):04x}'
                    for c in text[:limit])
    return shown + ('...' if len(text) > limit else '')


def say(message='', *, end='\n'):
    print(message, end=end, flush=True)


def warn(message):
    print('WARNING: ' + message, file=sys.stderr, flush=True)


def search_path():
    """Absolute PATH entries only: relative entries would resolve inside the candidate checkout."""
    entries = [entry for entry in os.environ.get('PATH', '').split(os.pathsep) if entry.startswith('/')]
    if PINNED_CODEX.is_dir():
        entries.insert(0, str(PINNED_CODEX))
    return os.pathsep.join(dict.fromkeys(entries or ['/usr/bin', '/bin']))


def tool(name, required=True):
    found = shutil.which(name, path=search_path())
    require(found or not required, f'{name} not found on PATH; see docs/dev-setup.md')
    return found


def child_env(*extra):
    """Explicit environment for trusted helper processes; secrets only when named."""
    env = {'PATH': search_path(), 'HOME': str(Path.home()), 'LANG': os.environ.get('LANG', 'C.UTF-8'),
           'PYTHONDONTWRITEBYTECODE': '1'}
    for key in ('TMPDIR', 'LC_ALL', 'LC_CTYPE', 'GH_CONFIG_DIR', 'FACTORY_DOCKER_HOST', *extra):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def git(root, *args, network=False, input=None, check=True, timeout=120, env=None, interactive=False):
    """Hardened Git: no hooks, fsmonitor, global/system config, attribute files, replace objects or lazy fetches."""
    command = [tool('git'), '--no-pager', '--no-replace-objects', '-C', str(root), *GIT_SAFETY]
    if network:
        command += ['-c', 'credential.helper=',
                    '-c', 'credential.https://github.com.helper=!' + shlex.quote(tool('gh')) + ' auth git-credential']
    environment = {'PATH': search_path(), 'HOME': str(Path.home()), 'LANG': 'C', 'GIT_CONFIG_GLOBAL': os.devnull,
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ATTR_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0',
                   'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': NETWORK_PROTOCOLS if network else '',
                   **(env or {})}
    if network and os.environ.get('GH_CONFIG_DIR'):
        environment['GH_CONFIG_DIR'] = os.environ['GH_CONFIG_DIR']
    if interactive:  # e.g. the commit message editor: needs the terminal
        environment['TERM'] = os.environ.get('TERM', 'xterm')
        result = subprocess.run(command + list(args), env=environment)
        require(result.returncode == 0 or not check, f'git {args[0]} failed or was aborted')
        return result
    result = subprocess.run(command + list(args), env=environment, input=input, capture_output=True, timeout=timeout)
    if check and result.returncode:
        detail = printable(result.stderr.decode(errors='replace').strip()[-600:], 600)
        raise Blocked(f'git {args[0]} failed in {root}: {detail}')
    return result


def out(root, *args, **kwargs):
    return git(root, *args, **kwargs).stdout.decode().strip()


def is_ancestor(root, older, newer):
    return git(root, 'merge-base', '--is-ancestor', older, newer, check=False).returncode == 0


class Lock:
    """fcntl lock with a holder note; the kernel releases it when the holder dies."""
    def __init__(self, path, what):
        self.path, self.what, self.handle = Path(path), what, None

    def acquire(self, *, wait=None, exclusive=True):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handle = open(self.path, 'a+')
        deadline = time.monotonic() + (LOCK_WAIT if wait is None else wait)
        while True:
            try:
                fcntl.flock(self.handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    holder = self.holder()
                    self.handle.close()
                    self.handle = None
                    raise Blocked(f'{self.what} is busy' + (f' (held by {holder})' if holder else '')
                                  + '; wait for that command or stop it, then retry') from None
                time.sleep(0.2)
        if exclusive:
            note = self.path.with_suffix('.holder')
            atomic_json(note, {'pid': os.getpid(), 'command': ' '.join(sys.argv[1:3]) or 'factory',
                               'since': time.strftime('%Y-%m-%d %H:%M:%S')})
        return self

    def holder(self):
        try:
            data = json.loads(self.path.with_suffix('.holder').read_text())
            return f"pid {int(data['pid'])}, factory {printable(data['command'], 80)}, since {printable(data['since'], 30)}"
        except (OSError, ValueError, KeyError, TypeError):
            return ''

    def release(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        return self.acquire() if self.handle is None else self

    def __exit__(self, *_):
        self.release()


def held(path):
    """True while another process holds the lock at path (runner liveness)."""
    if not Path(path).exists():
        return False
    with open(path, 'a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temp = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def checked_target(root, relative):
    """A path below root whose existing components are real directories, never symlinks."""
    safe_path(relative)
    current = Path(root)
    for part in relative.split('/')[:-1]:
        current = current / part
        if os.path.lexists(current):
            require(not current.is_symlink() and current.is_dir(), f'unsafe path component in checkout: {current}')
    target = Path(root) / relative
    require(not target.is_symlink(), f'refusing to follow a symlink: {target}')
    return target


def write_new(root, relative, data):
    target = checked_target(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
    return target


def replace_file(root, relative, data):
    target = checked_target(root, relative)
    require(not os.path.lexists(target) or target.is_file(), f'not a regular file: {target}')
    descriptor, temp = tempfile.mkstemp(prefix='.factory-', dir=target.parent)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
    os.chmod(temp, 0o644)
    os.replace(temp, target)


def read_regular(root, relative, limit=2_000_000):
    target = checked_target(root, relative)
    require(target.is_file(), f'not a regular file: {target}')
    require(target.stat().st_size <= limit, f'file too large: {target}')
    return target.read_bytes()


def remove_file(root, relative):
    target = checked_target(root, relative)
    require(target.is_file(), f'not a regular file: {target}')
    target.unlink()


def ask(question):
    """Explicit confirmation from the person at the terminal; never assumed."""
    require(sys.stdin.isatty(), 'confirmation needed: run this command in an interactive terminal')
    answer = input(question + ' [y/N] ').strip().lower()
    return answer in ('y', 'yes')


def countdown(message, seconds=5):
    warn(message)
    for left in range(seconds, 0, -1):
        say(f'  continuing in {left} s (Ctrl-C to abort)', end='\r')
        time.sleep(1)
    say(' ' * 40, end='\r')


def feed(stream, data):
    def write():
        try:
            stream.write(data)
        except OSError:
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass
    thread = threading.Thread(target=write, daemon=True)
    thread.start()
    return thread


DOCKER_WAIT = 120  # seconds: Docker Desktop starting up, or waking from its resource saver, answers late


def wait_for_docker(image, timeout=DOCKER_WAIT, interval=2, clock=time.monotonic, sleep=time.sleep):
    """Wait until Docker answers and holds `image`, nudging it awake: a Docker Desktop engine that does not answer is
    started (`docker desktop start`, unless FACTORY_DOCKER_HOST names another engine), and when the image seems missing
    one throwaway container is run from it, because Docker Desktop's resource saver answers queries without its VM
    (and may then call a present image missing) while only a container run wakes the VM. Says once that it waits.
    Returns (endpoint, problem): problem None when ready, 'docker' when Docker never answered, 'image' when the image
    is not there (decided soon after Docker answers, never only at the end)."""
    docker = tool('docker', required=False)
    if not docker:
        return '', 'docker'
    host = docker_host()
    env = {**child_env(), **({'DOCKER_HOST': host} if host else {})}

    def answer(*args, wait=30):
        try:
            result = subprocess.run([docker, *args], capture_output=True, text=True, env=env, timeout=wait)
        except subprocess.TimeoutExpired:
            return None
        return result.stdout if result.returncode == 0 else None
    deadline, answered, announced, started, woken = clock() + timeout, None, False, False, False
    while True:
        if answer('info', '--format', '{{.ServerVersion}}') is not None:
            answered = answered or clock()
            if answer('image', 'inspect', '--format', '{{.Id}}', image) is not None:
                return host, None
            if not woken:
                # Wake the VM: a no-op container without network, capabilities or writes; never pull a missing image.
                woken = True
                answer('run', '--rm', '--pull', 'never', '--network', 'none', '--cap-drop', 'ALL', '--read-only',
                       '--entrypoint', 'true', image, wait=60)
                continue
            # A listed image is still loading into the image store; an unlisted one is missing.
            if not (answer('image', 'ls', '--quiet', image) or '').strip() and clock() - answered >= 10:
                return host, 'image'
        elif not started and not os.environ.get('FACTORY_DOCKER_HOST'):
            started = True  # Docker Desktop stopped or still starting: start it and wait for its engine (no-op if running)
            say('Starting Docker Desktop…')
            answer('desktop', 'start', '--timeout', str(max(1, int(deadline - clock()))), wait=max(1, deadline - clock()))
            continue
        if clock() >= deadline:
            return host, 'image' if answered else 'docker'
        if not announced:
            say(f'Waiting for Docker to be ready, up to {timeout} s…')
            announced = True
        sleep(interval)


def docker_host():
    """The Docker endpoint for factory containers: FACTORY_DOCKER_HOST, else the active Docker context."""
    if os.environ.get('FACTORY_DOCKER_HOST'):
        return os.environ['FACTORY_DOCKER_HOST']
    docker = tool('docker', required=False)
    if not docker:
        return ''
    result = subprocess.run([docker, 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'],
                            capture_output=True, text=True, env=child_env(), timeout=30)
    return result.stdout.strip() if result.returncode == 0 else ''
