"""Sandboxed docker runs for the deterministic test stage. Standard library only, trusted host code.

Every step runs in the trusted test image with the same isolation: no network, read-only root, no capabilities, no new
privileges, bounded processes, memory and CPU, a small tmpfs /tmp, no Docker socket and no environment beyond what the
caller passes. Output goes to a host file outside every mount, never into the job log, so a PR cannot inject workflow
commands. A timeout removes the container, which subprocess's own timeout would leave running."""
import os
import re
import stat
import subprocess
import time
from pathlib import Path

import images

FLAGS = ['--rm', '--init', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
         '--pids-limit', '256', '--memory', '2g', '--cpus', '2', '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m']
MAX_TAIL = 64 * 1024
UNSAFE = re.compile(r'[,=\x00-\x1f\x7f]')


def argv(image_id, command, name, mounts=(), env=None, workdir='/work', user=None):
    """docker run argv: FLAGS, a container name for cleanup, no log copy in the daemon, the given bind mounts
    ((host, container, readonly)) and environment; nothing else from the host."""
    if not images.IMAGE_ID.fullmatch(image_id):
        raise ValueError('expected a content-addressed test image')
    result = ['docker', 'run', *FLAGS, '--name', name, '--log-driver', 'none']
    if user:
        result += ['--user', user]
    for source, destination, readonly in mounts:
        if not (str(source).startswith('/') and destination.startswith('/')) or UNSAFE.search(str(source) + destination):
            raise ValueError('unsafe mount')
        result += ['--mount', f'type=bind,src={source},dst={destination}' + (',readonly' if readonly else '')]
    for key, value in (env or {}).items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or '\n' in value or '\x00' in value:
            raise ValueError('unsafe environment variable')
        result += ['--env', f'{key}={value}']
    return result + ['--workdir', workdir, image_id, *command]


def run(command, name, timeout, log, run=None, clock=time.monotonic):
    """Run a docker command with stdout and stderr in the host file `log`. Returns (exit code or None on timeout,
    seconds). On a timeout the container is removed by name."""
    run = run or subprocess.run
    started = clock()
    with open(log, 'wb') as output:
        try:
            result = run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout, env=images.docker_env())
        except subprocess.TimeoutExpired:
            run(['docker', 'rm', '--force', name], capture_output=True, timeout=60, env=images.docker_env())
            return None, round(clock() - started, 1)
    return result.returncode, round(clock() - started, 1)


def tail(log, limit=MAX_TAIL):
    """The last `limit` bytes of a log, decoded leniently."""
    try:
        with open(log, 'rb') as file:
            file.seek(max(0, os.fstat(file.fileno()).st_size - limit))
            return file.read(limit).decode('utf-8', 'replace')
    except OSError:
        return ''


class Deadline:
    """One time budget for every dependency fetch and step after the image is ready."""
    def __init__(self, seconds, clock=time.monotonic):
        self.clock, self.end = clock, clock() + seconds

    def remaining(self, limit):
        return max(0, min(limit, int(self.end - self.clock())))


def read_results(directory, suffix, max_files=20, limit=8 * 1024 * 1024):
    """Result files a step wrote: regular files only (no symlinks, FIFOs or directories), never followed, each within
    `limit` bytes, at most `max_files`. Returns (contents, number of refused entries)."""
    files, problems = [], 0
    try:
        entries = os.scandir(directory)
    except OSError:
        return [], 0
    with entries:
        for entry in entries:
            if not entry.name.endswith(suffix):
                continue
            if len(files) >= max_files:
                problems += 1
                break
            try:
                descriptor = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                problems += 1
                continue
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                os.close(descriptor)
                problems += 1
                continue
            with os.fdopen(descriptor, 'rb') as file:
                files.append(file.read(limit + 1))
    return files, problems


def lstat_path(root, relative):
    """lstat of `relative` under `root`, or None if any component is missing or a symlink, or the path is unsafe."""
    parts = relative.split('/') if relative else []
    if not parts or any(part in ('', '.', '..') for part in parts):
        return None
    path, info = Path(root), None
    for part in parts:
        path = path / part
        try:
            info = os.lstat(path)
        except OSError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return None
    return info


def regular(root, relative):
    info = lstat_path(root, relative)
    return info is not None and stat.S_ISREG(info.st_mode)


def directory(root, relative):
    info = lstat_path(root, relative)
    return info is not None and stat.S_ISDIR(info.st_mode)
