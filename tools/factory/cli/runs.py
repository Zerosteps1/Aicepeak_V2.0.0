"""Background runs: registry, spawn, attach, stop, cancel and stale detection.

A run lives in STATE_DIR/runs/<id>/. Its runner holds an fcntl lock on `lock` for its whole life, so liveness
needs no process inspection: a free lock with an unfinished status means the runner died.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import tempfile
import time

import common
from common import Blocked, require, say

TERMINAL = ('completed', 'stopped', 'failed', 'cancelled')
EXIT = {'completed': 0, 'stopped': 0, 'failed': 1, 'cancelled': 130}
LABEL = 'aicepeak.factory.run'
CANCEL_GRACE = 45
POLL = 0.5


def root():
    return common.STATE_DIR / 'runs'


def create(order, kind):
    path = root() / f'{order}-{time.strftime("%Y%m%d-%H%M%S")}-{os.urandom(2).hex()}'
    path.mkdir(parents=True, mode=0o700)
    (path / 'lock').touch(mode=0o600)
    (path / 'log').touch(mode=0o600)
    return path


def claim(path):
    """Hold the run lock from creation on; spawn hands it to the runner, so the run is never seen as dead."""
    handle = open(path / 'lock', 'a')
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def state(path):
    try:
        return json.loads((Path(path) / 'run.json').read_text())
    except (OSError, ValueError):
        return {}


def update(path, **values):
    data = state(path)
    data.update(values)
    common.atomic_json(Path(path) / 'run.json', data)
    return data


def alive(path):
    return common.held(Path(path) / 'lock')


def every():
    if not root().is_dir():
        return []
    return sorted((p for p in root().iterdir() if (p / 'run.json').is_file()), key=lambda p: p.stat().st_mtime, reverse=True)


def active(order=None):
    return [path for path in every() if alive(path) and (order is None or state(path).get('order') == order)]


def find(order=None):
    """The active run of a work order (or the only active run)."""
    running = active(order)
    if order is None:
        require(len(running) <= 1, 'several runs are active: name the work order, e.g. `factory continue 7`')
    if running:
        return running[0]
    last = next((path for path in every() if order is None or state(path).get('order') == order), None)
    if last:
        settle_stale(last)
        data = state(last)
        raise Blocked(f'no active run{" for " + order if order else ""}; the last run {last.name} ended '
                      f'{data.get("status", "unknown")}' + (f' ({data["reason"]})' if data.get('reason') else '')
                      + f'. Log: {last / "log"}')
    raise Blocked(f'no run{" for " + order if order else ""} found')


def spawn(path, python, keys, lock):
    """Start the runner from the run's pinned trusted export; keys travel over a pipe, never env or argv."""
    script = path / 'trusted/tools/factory/cli/factory.py'
    read, write = os.pipe()
    with open(path / 'log', 'ab', buffering=0) as log:
        process = subprocess.Popen([python, '-I', '-S', '-B', str(script), '_run', path.name, '--keys-fd', str(read),
                                    '--lock-fd', str(lock.fileno())], pass_fds=(read, lock.fileno()),
                                   start_new_session=True, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, cwd=path, env=common.child_env())
    os.close(read)
    lock.close()  # the runner keeps the same lock
    update(path, pid=process.pid)  # session leader: its pid is also its process group
    with os.fdopen(write, 'w') as stream:
        json.dump(keys, stream)
    caffeinate = common.tool('caffeinate', required=False)
    if caffeinate:  # keeps the Mac from idle-sleeping while the run lives; ends with the runner
        subprocess.Popen([caffeinate, '-i', '-w', str(process.pid)], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process.pid


def follow(path, reattach):
    """Show the run's log as it grows. Ctrl-C only detaches; the run goes on."""
    say(f'Run {path.name} (log: {path / "log"})')
    say(f'Ctrl-C detaches. Reattach: factory continue {reattach} · stop after this step: factory stop workorder '
        f'{reattach} · cancel now: factory cancel workorder {reattach}')
    try:
        with open(path / 'log', 'rb') as handle:
            while True:
                chunk = handle.read()
                if chunk:
                    text = chunk.decode('utf-8', 'replace')
                    sys.stdout.write(common.printable(text, len(text)))  # the log can quote model-chosen names
                    sys.stdout.flush()
                elif not alive(path):
                    rest = handle.read().decode('utf-8', 'replace')
                    sys.stdout.write(common.printable(rest, len(rest)))
                    break
                else:
                    time.sleep(POLL)
    except KeyboardInterrupt:
        say(f'\nDetached; the run continues. Reattach: factory continue {reattach}')
        return 0
    settle_stale(path)
    data = state(path)
    say(f'Run {path.name} ended: {data.get("status", "unknown")}' + (f' ({data["reason"]})' if data.get('reason') else ''))
    return EXIT.get(data.get('status'), 1)


def stop(path):
    (path / 'stop').touch(mode=0o600)
    data = update(path, stop_requested=True)
    say(f'Stop requested: {path.name} ends after its current step ({data.get("step", "starting")}) and applies what exists.')


def cancel(path):
    """Cancel now: the runner forwards SIGTERM to its child and cleans up; anything left is killed and swept."""
    data = state(path)
    pid = data.get('pid')
    if alive(path) and isinstance(pid, int):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + CANCEL_GRACE
        while alive(path) and time.monotonic() < deadline:
            time.sleep(POLL)
        if alive(path):
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(1)
    sweep(path)
    data = state(path)
    if data.get('status') not in TERMINAL:
        data = update(path, status='cancelled', reason='cancelled', ended=time.strftime('%Y-%m-%d %H:%M:%S'))
    say(f'Run {path.name}: {data["status"]}. No GitHub state was changed by the cancel.')
    if data.get('pr'):  # factory.yml always runs from the config branch
        say(f'Pull request #{data["pr"]} stays open. Pause it: gh pr ready {data["pr"]} --undo · close it: '
            f'gh pr close {data["pr"]} --comment "<reason>" · a claimed review that got stuck: gh workflow run '
            f'factory.yml --ref {data.get("config_branch") or "<config branch>"} -f pr={data["pr"]} -f retry=true')


def settle_stale(path):
    """A free lock with an unfinished status: the runner died. Remove its labelled containers and record it.
    Never signal by pid here: after a reboot that number can belong to anything."""
    data = state(path)
    if alive(path) or data.get('status') in TERMINAL or not data:
        return
    sweep(path)
    update(path, status='failed', reason='the runner ended unexpectedly', ended=time.strftime('%Y-%m-%d %H:%M:%S'))


def sweep(path, value=None, host=None):
    """Remove every Docker container, network and volume that carries this run's label (twice: late creations)."""
    docker = common.tool('docker', required=False)
    if not docker:
        return
    host = host if value else state(path).get('docker_host')
    with tempfile.TemporaryDirectory(prefix='factory-sweep-') as config:
        env = {**common.child_env(), 'DOCKER_CONFIG': config, **({'DOCKER_HOST': host} if host else {})}
        selector = f'label={LABEL}={value or path.name}'
        for attempt in range(2):
            for listing, remove in ((['ps', '-aq'], ['rm', '-f']), (['network', 'ls', '-q'], ['network', 'rm']),
                                    (['volume', 'ls', '-q'], ['volume', 'rm', '-f'])):
                found = subprocess.run([docker, *listing, '--filter', selector], capture_output=True, text=True,
                                       env=env, timeout=30)
                if found.returncode == 0 and found.stdout.split():
                    subprocess.run([docker, *remove, *found.stdout.split()], capture_output=True, env=env, timeout=60)
            if attempt == 0:
                time.sleep(1)


def listing():
    rows = []
    for path in every()[:15]:
        settle_stale(path)
        data = state(path)
        live = alive(path)
        rows.append(f'{"▶" if live else " "} {data.get("order", "?"):<18} {data.get("kind", "?"):<7} '
                    f'{(data.get("step") if live else data.get("status")) or "?":<16} {data.get("started", ""):<19} '
                    f'{data.get("branch", "")}' + (f'  PR #{data["pr"]}' if data.get('pr') else ''))
    if not rows:
        say('No factory runs on this device yet. Start one with `factory start workorder <n>`.')
        return 0
    say('  work order         kind    step/status      started             branch')
    for row in rows:
        say(row)
    if active():
        say('Reattach to a running one: factory continue <n>')
    return 0
