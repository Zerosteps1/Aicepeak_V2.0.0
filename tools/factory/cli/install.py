"""Installer stage 2 (`factory _install`): sets up this device from the control checkout.

Stage 1 (install-factory-cli.sh) only checks prerequisites, verifies itself against the config branch's copy and
clones the control checkout on the chosen control branch; everything else runs here, from that reviewed code.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

import checkouts
import common
from common import require, say
import session

MARKER = '# aicepeak factory CLI shim (managed by tools/factory/cli/install-factory-cli.sh)'
BLOCK = ('# >>> aicepeak factory cli >>>', '# <<< aicepeak factory cli <<<')
RC_FILE = Path.home() / '.zshrc'


def write_shim(target, python, control):
    """Atomic; an existing file is only replaced when it is our own shim."""
    if os.path.lexists(target):
        require(not target.is_symlink() and target.is_file() and MARKER in target.read_text(errors='replace'),
                f'{target} exists and is not the factory shim; remove it or choose --bin-dir')
    script = ('#!/bin/sh\n' + MARKER + '\nexec ' + shlex.quote(python) + ' -I -S -B '
              + shlex.quote(str(control / 'tools/factory/cli/factory.py')) + ' "$@"\n')
    temp = target.with_name('.factory-shim.tmp')
    temp.write_text(script)
    temp.chmod(0o755)
    os.replace(temp, target)


def path_block(bin_dir):
    if str(bin_dir) in os.environ.get('PATH', '').split(os.pathsep):
        return False
    text = RC_FILE.read_text() if RC_FILE.is_file() else ''
    if BLOCK[0] in text:
        return False
    with RC_FILE.open('a') as handle:
        handle.write(f'\n{BLOCK[0]}\nexport PATH="$PATH":{shlex.quote(str(bin_dir))}\n{BLOCK[1]}\n')
    return True


def ensure_identity(candidate):
    for key in ('name', 'email'):
        if common.out(candidate, 'config', '--local', '--get', f'user.{key}', check=False):
            continue
        found = subprocess.run([common.tool('git'), 'config', '--global', '--get', f'user.{key}'], capture_output=True, text=True)
        default = found.stdout.strip()
        require(sys.stdin.isatty() or default, f'set user.{key} for the candidate: git -C {candidate} config --local user.{key} ...')
        value = (input(f'Git user.{key} for commits in the candidate [{default}]: ').strip() if sys.stdin.isatty() else '') or default
        require(value, f'user.{key} is required for commits')
        common.git(candidate, 'config', '--local', f'user.{key}', value)


def store_keys(force):
    security = common.tool('security', required=False) if sys.platform == 'darwin' else None
    if not security:
        say('Author keys: export ANTHROPIC_API_KEY and CONTEXT7_API_KEY before author runs (no macOS keychain here).')
        return
    for name, service in common.AUTHOR_KEYS.items():
        present = subprocess.run([security, 'find-generic-password', '-s', service], capture_output=True).returncode == 0
        if present and not force:
            say(f'Author key {name}: stored in the keychain ({service}).')
            continue
        if not sys.stdin.isatty() or not common.ask(f'Store {name} in your login keychain as {service} now?'):
            say(f'Author key {name}: not stored; export it before author runs or rerun with --author-keys.')
            continue
        say(f'Paste {name} at the hidden prompt twice; it is not shown and not saved anywhere else.')
        subprocess.run([security, 'add-generic-password', '-U', '-a', os.environ.get('USER', ''), '-s', service, '-w'],
                       check=False)


def install(control_dir, candidate_dir, bin_dir, author_keys=False, branch=None):
    control = Path(control_dir).expanduser().resolve()
    require(os.path.samefile(control / 'tools/factory/cli/factory.py', Path(__file__).resolve().parent / 'factory.py'),
            'the installer must run from the control checkout it installs')
    require(sys.version_info >= (3, 11) and os.path.isabs(sys.executable), 'Python 3.11 or newer is required')
    control = checkouts.toplevel(control)
    config = checkouts.repository_config(control)
    branch = branch or config['config_branch']
    with common.Lock(common.STATE_DIR / 'locks/control.lock', 'the control checkout'):
        sha, _ = checkouts.update_control(control, config, branch=branch)  # refuses an unlisted control branch
        policy = checkouts.read_policy(control, config)
    say(f'Control checkout: {control} ({branch} {sha[:12]}; rules from {policy.model.config_branch} {policy.tip[:12]})')
    candidate = Path(candidate_dir).expanduser().absolute()
    if not os.path.lexists(candidate):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        common.git(candidate.parent, 'clone', '--quiet', checkouts.github_url(config), str(candidate), network=True, timeout=600)
        say(f'Cloned the candidate checkout: {candidate}')
    candidate = checkouts.toplevel(candidate)
    checkouts.separate(control, candidate)
    session.identity(candidate, policy.config)
    ensure_identity(candidate)
    checkouts.verify_candidate(candidate, policy.config)
    say(f'Candidate checkout: {candidate}')
    bin_path = Path(bin_dir).expanduser().absolute()
    bin_path.mkdir(parents=True, exist_ok=True)
    write_shim(bin_path / 'factory', sys.executable, control)
    common.atomic_json(common.CONFIG_FILE, {'control': str(control), 'candidate': str(candidate),
                                            'python': sys.executable, 'bin': str(bin_path), 'branch': branch})
    say(f'Installed {bin_path / "factory"} (configuration: {common.CONFIG_FILE})')
    if path_block(bin_path):
        say(f'Added {bin_path} to PATH in {RC_FILE}; open a new terminal before using `factory`.')
    store_keys(author_keys)
    say('Done. Next: `factory doctor`, then `factory --help`.')
    return 0
