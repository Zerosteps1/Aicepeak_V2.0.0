#!/usr/bin/env python3
"""factory – the maintainer's daily command for the Aicepeak software factory.

Installed once per device by tools/factory/cli/install-factory-cli.sh. It runs trusted code only from the clean
control checkout on its listed control branch (or a run's pinned export of it), takes every rule from the config
branch tip and acts on the configured candidate checkout, whatever the current directory. See docs/factory-cli.md.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(HERE.parent)]
import branches  # noqa: E402  standard library only
import helptext  # noqa: E402  standard library only

VERSION = '0.5.0'
LOCAL = ('status', 'continue', 'stop', 'cancel')  # no network, no policy
REEXEC = 'FACTORY_CLI_REEXEC'
REEXECS = int(os.environ.pop(REEXEC, '0') or 0)  # never inherited by editors or other children
ISSUE_HELP = 'the work order: its GitHub issue number, 57 or "#57"'


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

    def work_order(item):
        item.add_argument('noun', choices=('workorder',), metavar='workorder')
        item.add_argument('workorder', metavar='<issue>', help=ISSUE_HELP)

    item = command('submit')
    item.add_argument('--title', help='commit title (default: "<issue title> #57"); with --finished also the PR title')
    item.add_argument('--desc', help='commit description; with --finished also the PR description')
    item.add_argument('--finished', action='store_true', help='open the pull request for the work order (or watch the open one)')
    work_order(command('start'))
    for name in ('continue', 'stop', 'cancel'):
        item = command(name)
        item.add_argument('noun', choices=('workorder', 'hotfix'), metavar='workorder <issue> | hotfix',
                          help='`workorder <issue>` names the run of a work order; `hotfix` the hotfix without one')
        item.add_argument('workorder', nargs='?', metavar='<issue>', help=ISSUE_HELP)
    item = command('fix')
    work_order(item)
    item.add_argument('prompt', nargs='?', help='the problem, or "#N" / a GitHub URL of a maintainer-written issue or comment')
    item = command('hotfix')
    item.add_argument('words', nargs='+', metavar='[workorder <issue>] ["prompt"]',
                      help=f'`workorder <issue>` ({ISSUE_HELP}) and an optional prompt, or only the prompt (the problem)')
    item = command('review')
    work_order(item)
    item.add_argument('prompt', help='what the reviewer should look for')
    item = command('watch')
    item.add_argument('pr', nargs='?', type=int, help='pull request number')
    item.add_argument('--all', action='store_true', help='every PR labelled awaiting-senior-review, until Ctrl-C')
    item = command('merge')
    item.add_argument('pr', type=int)
    item.add_argument('--dry-run', action='store_true', help='show the verdict only; merge nothing')
    item = command('promote')
    item.add_argument('branch', help='the validation branch to promote')
    item.add_argument('--to', help='the production branch (default: the only one listed)')
    item = command('update')
    item.add_argument('target', nargs='?', metavar='<target-branch>',
                      help='the branch to bring the config branch into (default: the branch checked out in the candidate)')
    item = command('branches')
    item.add_argument('--show', action='store_true', help='also write and open a self-contained HTML page')
    item = command('use', 'use branch')
    item.add_argument('noun', choices=('branch',), metavar='branch')
    item.add_argument('name', help='a listed production or validation branch')
    item = command('add', 'add validation branch')
    item.add_argument('level', choices=('validation', 'production'))
    item.add_argument('noun', choices=('branch',), metavar='branch')
    item.add_argument('name', help='lowercase letters, digits and inner hyphens, at most 40')
    item.add_argument('--gate', choices=branches.GATES, help='validation branches: full, tests or none')
    item.add_argument('--kinds', default='', help='validation branches: work-order kinds routed to it, e.g. factory,smoke')
    item.add_argument('--review', choices=branches.REVIEWS, help='production branches: no, initiated or maintainer-manual')
    item.description = (helptext.description('add validation branch') + '\n\n`factory add production branch`: '
                        + helptext.COMMANDS['add production branch']['what'])
    item.epilog = helptext.epilog('add validation branch') + '\n\n' + helptext.epilog('add production branch')
    item = command('remove', 'remove branch')
    item.add_argument('noun', choices=('branch',), metavar='branch')
    item.add_argument('name')
    item = command('set', 'set config branch')
    item.add_argument('what', choices=('config',), metavar='config')
    item.add_argument('noun', choices=('branch',), metavar='branch')
    item.add_argument('name', help='a listed production branch')
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
    hidden.add_argument('--branch', required=True)
    hidden.add_argument('--author-keys', action='store_true')
    return parser


def misuse(args):
    """Option combinations argparse cannot express; answered before any lock or network."""
    if args.command == 'add':
        kinds = [kind.strip() for kind in args.kinds.split(',') if kind.strip()]
        if args.level == 'validation' and (not args.gate or args.review):
            return '`factory add validation branch` needs --gate and takes no --review'
        if args.level == 'production' and (not args.review or args.gate or kinds):
            return '`factory add production branch` needs --review and takes no --gate or --kinds'
        if not set(kinds) <= set(branches.KINDS) or len(set(kinds)) != len(kinds):
            return '--kinds takes distinct values of ' + ', '.join(branches.KINDS)
        args.kinds = kinds
    if args.command in ('continue', 'stop', 'cancel'):
        if args.noun == 'workorder' and args.workorder is None:
            return f'`factory {args.command} workorder <issue>` needs the issue number, e.g. 57'
        if args.noun == 'hotfix' and args.workorder is not None:
            return f'`factory {args.command} hotfix` names the hotfix without a work order and takes no issue number'
    if args.command == 'hotfix':
        words = args.words
        if words[0] == 'workorder':
            if len(words) not in (2, 3):
                return '`factory hotfix workorder <issue> ["prompt"]` takes the issue number and at most one prompt'
            args.workorder, args.prompt = words[1], (words[2] if len(words) == 3 else None)
        elif len(words) == 1:
            args.workorder, args.prompt = None, words[0]
        else:
            return ('`factory hotfix` takes `workorder <issue>` and an optional prompt, or only a prompt in quotes: '
                    '`factory hotfix "<problem>"`')
        if args.prompt is not None and not args.prompt.strip():
            return 'the prompt is empty'
    return None


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
    """Paths, the pinned policy and lazily resolved GitHub identity for one command.

    sha is the control checkout's code; policy the config branch tip whose config.json (config) and branch model
    (model) every rule comes from. Local commands have no policy."""
    def __init__(self, device, config, sha, policy=None):
        import checkouts
        import common
        self.common, self.checkouts = common, checkouts
        self.root, self.device, self.sha = ROOT, device, sha
        self.control, self.candidate = device['control'], device['candidate']
        self.branch = device.get('branch') or config['config_branch']
        self.policy, self.config, self.model = (policy.tip, policy.config, policy.model) if policy else (None, config, None)
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

    def tips(self, *names):
        """Branches missing on GitHub are left out of the result."""
        with self.candidate_lock():
            return self.checkouts.fetch(self.candidate, self.config, *names)

    def tip(self, name):
        found = self.tips(name)
        self.common.require(name in found, f'branch {name} is not on GitHub')
        return found[name]

    def config_tip(self):
        """The newest config branch tip in the candidate: rules and the device smoke's work-order file come from
        here."""
        return self.tip(self.model.config_branch)

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
    config = checkouts.repository_config()  # the code's own copy: repository and the name of the config branch
    lock = common.Lock(common.STATE_DIR / 'locks/control.lock', 'the control checkout').acquire()
    policy = None
    try:
        local = command in LOCAL
        branch = device['branch'] or config['config_branch']
        sha, changed = checkouts.update_control(device['control'], config, branch=branch,
                                                online=not local and not REEXECS, listed=command != 'use')
        if device['branch'] is None:  # pin the verified branch: after a fast-forward the code may name another config branch
            checkouts.record_branch(branch)
            device['branch'] = branch
        if sha != before or changed:  # the code already imported may be older than the verified commit
            lock.release()
            reexec()
            lock.acquire()
        import branching  # noqa: F401  every module is imported while the control checkout is locked
        import commands  # noqa: F401
        import pipeline  # noqa: F401
        import runs  # noqa: F401
        import workorders  # noqa: F401
        if not local:  # fail closed: every network command needs the pinned config branch tip
            policy = checkouts.read_policy(device['control'], config)  # follows a finished change of the config branch
            common.require(policy, f'the config branch {config["config_branch"]} was never fetched; check your '
                           'network and gh login, then retry')
            common.require(command == 'use' or branch in policy.model.names,
                           checkouts.unlisted(branch, policy.model.config_branch))
            checkouts.separate(device['control'], device['candidate'])
            checkouts.verify_candidate(device['candidate'], policy.config)
    finally:
        lock.release()
    return Context(device, config, sha, policy)


def run_reference(args):
    import runs
    import workorders
    return runs.HOTFIX if args.noun == 'hotfix' else workorders.resolve(args.workorder)


def dispatch(args):
    if args.command == '_install':
        import install
        return install.install(args.control_dir, args.candidate_dir, args.bin_dir, args.author_keys, args.branch)
    if args.command == '_run':
        import pipeline
        import runs
        pinned = runs.root() / args.run_id / 'trusted/tools/factory/cli/factory.py'
        if not (pinned.is_file() and os.path.samefile(pinned, __file__)):
            raise ValueError('the runner only starts from its own pinned export')
        return pipeline.execute(args.run_id, args.keys_fd, args.lock_fd)
    ctx = bootstrap(args.command)
    import branching
    import commands
    import pipeline
    import runs
    candidate = ctx.candidate.resolve()
    here = Path.cwd().resolve()
    if args.command not in LOCAL + ('use',) and not (here == candidate or candidate in here.parents):
        ctx.common.say(f'(working on the candidate checkout {ctx.candidate})')
    if args.command == 'submit':
        return commands.submit(ctx, args.title, args.desc, args.finished)
    if args.command == 'start':
        return pipeline.launch(ctx, 'start', args.workorder)
    if args.command in ('fix', 'hotfix'):
        return pipeline.launch(ctx, args.command, args.workorder, args.prompt)
    if args.command == 'continue':
        path = runs.find(run_reference(args))
        return runs.follow(path, runs.state(path).get('order'))
    if args.command == 'stop':
        return runs.stop(runs.find(run_reference(args))) or 0
    if args.command == 'cancel':
        return runs.cancel(runs.find(run_reference(args))) or 0
    if args.command == 'review':
        return pipeline.review_now(ctx, args.prompt, args.workorder)
    if args.command == 'watch':
        ctx.common.require(bool(args.pr) != bool(args.all), 'name one pull request, or use --all')
        return commands.watch(ctx, args.pr, args.all)
    if args.command == 'merge':
        return commands.merge(ctx, args.pr, args.dry_run)
    if args.command == 'status':
        return runs.listing()
    if args.command == 'promote':
        return branching.promote(ctx, args.branch, args.to)
    if args.command == 'update':
        return branching.update(ctx, args.target)
    if args.command == 'branches':
        return branching.diagram(ctx, args.show)
    if args.command == 'use':
        return branching.use(ctx, args.name)
    if args.command == 'add' and args.level == 'validation':
        return branching.add_validation(ctx, args.name, args.gate, args.kinds)
    if args.command == 'add':
        return branching.add_production(ctx, args.name, args.review)
    if args.command == 'remove':
        return branching.remove(ctx, args.name)
    if args.command == 'set':
        return branching.set_config(ctx, args.name)
    return commands.doctor(ctx)


def entry(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    problem = misuse(args)
    if problem:
        parser.error(problem)
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
    sys.exit(entry())
