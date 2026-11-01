#!/usr/bin/env python3
"""factory – the maintainer's daily command for the Aicepeak software factory.

Installed once per device by tools/factory/cli/install-factory-cli.sh. It runs trusted code only from the clean
control checkout on current main (or a run's pinned export of it) and acts on the configured candidate checkout,
whatever the current directory. See docs/factory-cli.md.
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(HERE.parent)]
import helptext  # noqa: E402  standard library only

VERSION = '0.1.0'
REEXEC = 'FACTORY_CLI_REEXEC'
REEXECS = int(os.environ.pop(REEXEC, '0') or 0)  # never inherited by editors or other children


def build_parser():
    parser = argparse.ArgumentParser(prog='factory', description=helptext.overview(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    # Answered before any configuration, lock or network: the version of the code this shim runs.
    parser.add_argument('--version', action='version', version=f'factory {VERSION}')
    commands = parser.add_subparsers(dest='command', metavar='<command>')

    def command(name, key=None):
        key = key or name
        return commands.add_parser(name, help=helptext.COMMANDS[key]['summary'], description=helptext.description(key),
                                   epilog=helptext.epilog(key), formatter_class=argparse.RawDescriptionHelpFormatter)

    item = command('issue')
    item.add_argument('--title', help='work order title (you can also write it in the editor)')
    item.add_argument('--kind', choices=('factory', 'product', 'smoke'), default='factory', help='work order kind (default: factory)')
    item.add_argument('--noedit', action='store_true', help='only create the file and print its path')
    item = command('submit')
    item.add_argument('target', nargs='?', choices=('workorders',), help='`workorders`: submit work orders instead')
    item.description = helptext.description('submit') + '\n\n`factory submit workorders`: ' + helptext.COMMANDS['submit workorders']['what']
    item.epilog = helptext.epilog('submit') + '\n\n' + helptext.epilog('submit workorders')
    item.add_argument('--title', help='commit title (default: "<ID>: <work order title>"); with --finished also the PR title')
    item.add_argument('--desc', help='commit description; with --finished also the PR description')
    item.add_argument('--finished', action='store_true', help='open the pull request for the work order (or watch the open one)')
    item.add_argument('--draft', action='store_true', help='with --finished: open the PR as a draft')
    item.add_argument('--workorder', help='work order when the branch name does not name one (7, 007 or FACTORY-007)')
    item.add_argument('--context', action='append', default=[], help='extra repository file for the preflight (repeatable)')
    for name in ('start', 'stop', 'cancel'):
        item = command(name)
        item.add_argument('noun', choices=('workorder',), metavar='workorder')
        item.add_argument('workorder', help='7, 007 or FACTORY-007')
    item = command('continue')
    item.add_argument('workorder', nargs='?', help='work order of the run (default: the only active run)')
    for name in ('fix', 'hotfix'):
        item = command(name)
        item.add_argument('workorder', help='7, 007 or FACTORY-007')
        item.add_argument('prompt', nargs='?', help='the problem, or #N / a GitHub URL of a maintainer-written issue or comment')
        item.add_argument('--pr', type=int, help='the open PR to fix when several implement the work order')
    item = command('review')
    item.add_argument('prompt', help='what the reviewer should look for')
    item.add_argument('--workorder', help='add this work order as context')
    item = command('watch')
    item.add_argument('pr', nargs='?', type=int, help='pull request number')
    item.add_argument('--all', action='store_true', help='every PR labelled awaiting-senior-review, until Ctrl-C')
    item = command('merge')
    item.add_argument('pr', type=int)
    item.add_argument('--dry-run', action='store_true', help='show the verdict only; merge nothing')
    command('status')
    command('doctor')
    hidden = commands.add_parser('_run')
    hidden.add_argument('run_id')
    hidden.add_argument('--keys-fd', type=int, required=True)
    hidden.add_argument('--lock-fd', type=int, required=True)
    hidden = commands.add_parser('_install')
    hidden.add_argument('--control-dir', required=True)
    hidden.add_argument('--candidate-dir', required=True)
    hidden.add_argument('--bin-dir', required=True)
    hidden.add_argument('--author-keys', action='store_true')
    return parser


def control_head(root):
    """Read HEAD without running anything, before any repository module is imported."""
    git = root / '.git'
    try:
        ref = (git / 'HEAD').read_text().strip()
        if not ref.startswith('ref: '):
            return ref
        name = ref[5:]
        if (git / name).is_file():
            return (git / name).read_text().strip()
        for line in (git / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + name):
                return line.split()[0]
    except OSError:
        pass
    return ''


def reexec(fresh=False):
    count = 1 if fresh else REEXECS + 1
    if count > 2:  # never loop: the third start continues with what it verified
        return
    os.execve(sys.executable, [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), *sys.argv[1:]],
              {**os.environ, REEXEC: str(count)})


class Context:
    """Paths, configuration and lazily resolved GitHub identity for one command."""
    def __init__(self, device, config, sha):
        import checkouts
        import common
        self.common, self.checkouts = common, checkouts
        self.root, self.device, self.config, self.sha = ROOT, device, config, sha
        self.control, self.candidate = device['control'], device['candidate']
        self._gh = self._user = None

    @property
    def gh(self):
        if self._gh is None:
            self._gh = self.checkouts.github()
        return self._gh

    @property
    def login(self):
        if self._user is None:
            self._user = self.checkouts.maintainer(self.gh, self.config)
        return self._user['login']

    def candidate_lock(self):
        return self.common.Lock(self.common.STATE_DIR / 'locks/candidate.lock', 'the candidate checkout')

    def main(self):
        with self.candidate_lock():
            return self.checkouts.fetch(self.candidate, self.config, 'main')['main']

    def identity_values(self):
        return {key: self.common.out(self.candidate, 'config', '--local', '--get', f'user.{key}') for key in ('name', 'email')}

    def identity(self):
        values = self.identity_values()
        return ['-c', f'user.name={values["name"]}', '-c', f'user.email={values["email"]}']

    def reexec(self, fresh=False):
        reexec(fresh)


def bootstrap(command):
    """Verify, update and lock the control checkout before importing the rest of the CLI."""
    before = control_head(ROOT)
    import common
    import checkouts
    device = checkouts.device()
    common.require(os.path.samefile(device['control'] / 'tools/factory/cli/factory.py', __file__),
                   f'this is not the installed control checkout ({device["control"]}); run the `factory` command')
    config = checkouts.repository_config()
    lock = common.Lock(common.STATE_DIR / 'locks/control.lock', 'the control checkout').acquire()
    try:
        local = command in ('status', 'continue', 'stop', 'cancel')
        sha, changed = checkouts.update_control(device['control'], config, fetch=not local and not REEXECS)
        if sha != before or changed:  # the code already imported may be older than the verified commit
            lock.release()
            reexec()
            lock.acquire()
        import commands  # noqa: F401  every module is imported while the control checkout is locked
        import pipeline  # noqa: F401
        import runs  # noqa: F401
        import workorders  # noqa: F401
        if not local:
            checkouts.separate(device['control'], device['candidate'])
            checkouts.verify_candidate(device['candidate'], config)
    finally:
        lock.release()
    return Context(device, config, sha)


def run_reference(reference):
    import runs
    import workorders
    if reference is None:
        return None
    orders = sorted({runs.state(path).get('order') for path in runs.every()} - {None})
    return workorders.resolve(reference, orders)


def dispatch(args):
    if args.command == '_install':
        import install
        return install.install(args.control_dir, args.candidate_dir, args.bin_dir, args.author_keys)
    if args.command == '_run':
        import pipeline
        import runs
        pinned = runs.root() / args.run_id / 'trusted/tools/factory/cli/factory.py'
        if not (pinned.is_file() and os.path.samefile(pinned, __file__)):
            raise ValueError('the runner only starts from its own pinned export')
        return pipeline.execute(args.run_id, args.keys_fd, args.lock_fd)
    ctx = bootstrap(args.command)
    import commands
    import pipeline
    import runs
    candidate = ctx.candidate.resolve()
    here = Path.cwd().resolve()
    if args.command not in ('status', 'continue', 'stop', 'cancel') and not (here == candidate or candidate in here.parents):
        ctx.common.say(f'(working on the candidate checkout {ctx.candidate})')
    if args.command == 'issue':
        return commands.issue(ctx, args.title, args.kind, args.noedit)
    if args.command == 'submit':
        if args.target == 'workorders':
            ctx.common.require(not (args.title or args.desc or args.finished or args.draft or args.workorder or args.context),
                               '`factory submit workorders` takes no further options')
            return commands.submit_workorders(ctx)
        return commands.submit(ctx, args.title, args.desc, args.finished, args.draft, args.workorder, args.context)
    if args.command == 'start':
        return pipeline.launch(ctx, 'start', args.workorder)
    if args.command in ('fix', 'hotfix'):
        return pipeline.launch(ctx, args.command, args.workorder, args.prompt, args.pr)
    if args.command == 'continue':
        path = runs.find(run_reference(args.workorder))
        return runs.follow(path, runs.state(path).get('order'))
    if args.command == 'stop':
        return runs.stop(runs.find(run_reference(args.workorder))) or 0
    if args.command == 'cancel':
        return runs.cancel(runs.find(run_reference(args.workorder))) or 0
    if args.command == 'review':
        return pipeline.review_now(ctx, args.prompt, args.workorder)
    if args.command == 'watch':
        ctx.common.require(bool(args.pr) != bool(args.all), 'name one pull request, or use --all')
        return commands.watch(ctx, args.pr, args.all)
    if args.command == 'merge':
        return commands.merge(ctx, args.pr, args.dry_run)
    if args.command == 'status':
        return runs.listing()
    return commands.doctor(ctx)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    # Relative PATH entries would resolve inside the candidate checkout for every tool, also in session.py.
    os.environ['PATH'] = os.pathsep.join(entry for entry in os.environ.get('PATH', '').split(os.pathsep)
                                         if entry.startswith('/')) or '/usr/bin:/bin'
    try:
        from contracts import Blocked
    except ImportError:
        Blocked = ValueError
    try:
        return dispatch(args)
    except KeyboardInterrupt:
        print('STOPPED: interrupted', file=sys.stderr)
        return 130
    except (Blocked, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
