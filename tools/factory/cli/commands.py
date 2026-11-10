"""Foreground factory commands: submit, watch, merge and doctor."""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import time

import checkouts
import common
from common import Blocked, git, is_ancestor, out, require, say, warn
import workorders

WATCH_ALL_INTERVAL = 60


def approvals(model):
    needed = model.work_order_approvals
    return (f'Next: {needed} maintainer{"" if needed == 1 else "s"} other than its author approve{"s" if needed == 1 else ""} '
            'the pull request at its current head; a maintainer merges it on GitHub (`factory merge` never merges into a '
            'production branch).')


def editor_command():
    return os.environ.get('VISUAL') or os.environ.get('EDITOR') or 'vi'


def show_diff(path, before, after):
    lines = difflib.unified_diff((before or b'').decode('utf-8', 'replace').splitlines(),
                                 (after or b'').decode('utf-8', 'replace').splitlines(),
                                 f'a/{path}', f'b/{path}', lineterm='')
    say(common.printable('\n'.join(lines), 20000))


def blob(repo, sha, path):
    result = git(repo, 'cat-file', 'blob', f'{sha}:{path}', check=False)
    return result.stdout if result.returncode == 0 else None


# --- submit ------------------------------------------------------------------------------------------

def run_session_submit(ctx, snapshot, args, on_created=None):
    """on_created runs as soon as session.py prints the new PR, not only after the review watch that follows."""
    with checkouts.policy_checkout(ctx.control, ctx.policy, ctx.config) as policy:
        command = checkouts.tool_command(policy, 'session.py', 'submit', '--candidate', snapshot, *args)
        process = subprocess.Popen(command, cwd=policy, env=checkouts.tool_env(), stdout=subprocess.PIPE, text=True)
        created = None
        try:
            for line in process.stdout:
                say(common.printable(line.rstrip('\n'), 20000))
                if created is None and line.startswith('{"pr":'):
                    try:
                        created = json.loads(line)
                    except ValueError:
                        continue
                    say(f'Pull request #{created["pr"]} created: {created["url"]}')
                    if on_created:
                        on_created(created['pr'])
            code = process.wait()
        except KeyboardInterrupt:
            checkouts.settle(process)
            raise
    if not created and code:
        say('No pull request was created.')
    return created['pr'] if created else None


def session_submit(ctx, snapshot, task, title, body_file, context=(), on_created=None, *, base):
    """`base` is a validation branch, or a production branch for config PRs. Config PRs carry no task and so get no
    advisory preflight: maintainer approvals and factory/deterministic decide them. `context` lists the unchanged
    modules that changed Python files import directly (checkouts.direct_imports)."""
    args = [*(['--task', task] if task else []), '--base', base, '--runner', ctx.config['runners'][0], '--title', title,
            '--body-file', body_file]
    for path in context:
        args += ['--context', path]
    return run_session_submit(ctx, snapshot, args, on_created)


def preflight(ctx, snapshot, task, context=(), *, base):
    """Advisory Astra preflight through session.py; returns the parsed review (or raises with the reason)."""
    with checkouts.policy_checkout(ctx.control, ctx.policy, ctx.config) as policy:
        args = ['preflight', '--candidate', snapshot, '--task', task, '--base', base]
        for path in context:
            args += ['--context', path]
        code, stdout, stderr = checkouts.run_tool(policy, 'session.py', *args, capture=True)
    result = checkouts.last_json(stdout)
    require(result and 'review' in result, 'preflight did not run: ' + checkouts.blocked_reason(stderr))
    return result['review']


def describe_review(review):
    say(f'Preflight: {review["outcome"]} – {common.printable(review["summary"], 2000)}')
    for finding in review.get('findings', []):
        say(f'  {finding["priority"]} {finding["id"]} {finding["file"]}:{finding.get("line")} '
            f'{common.printable(finding.get("impact", ""), 500)}')
    for item in review.get('limitations', []):
        say('  limitation: ' + common.printable(item, 500))


def open_pull_for(ctx, branch):
    found = [pull for pull in workorders.open_pulls(ctx.gh, ctx.config) if pull['head']['ref'] == branch]
    return found[0] if found else None


def finish_open_pr(ctx, pull, sha, branch, task, context):
    """A draft is a PR a maintainer paused with `gh pr ready --undo`: it becomes ready again only after a passing
    preflight."""
    number = pull['number']
    if pull.get('draft'):
        with checkouts.candidate_snapshot(ctx.candidate, ctx.control, sha, branch, ctx.config) as snapshot:
            review = preflight(ctx, snapshot, task, context, base=pull['base']['ref'])
        describe_review(review)
        if review['outcome'] != 'pass':
            say(f'Pull request #{number} stays a draft; fix the findings and run `factory submit --finished` again.')
            return 1
        ctx.gh.command(['pr', 'ready', str(number), '--repo', ctx.config['repository']])
        say(f'Pull request #{number} is ready for review.')
    if ctx.model.level(pull['base']['ref']) == 'production':  # no senior review to watch for
        say(approvals(ctx.model))
        return 0
    say(f'Watching pull request #{number}; Ctrl-C stops watching (the PR keeps waiting for a watcher).')
    return watch(ctx, number)


def read_order(ctx, policy, order):
    text, spec = workorders.read(ctx.gh, ctx.candidate, ctx.config, policy, order)
    require(workorders.is_issue(order) or spec['kind'] == 'smoke', f'{order} is a work-order file; apart from the '
            'device smoke (kind smoke) every work order is a GitHub issue')
    return text, spec


ISSUE_BRANCH_HINT = 'the branch of a work-order issue is named `<issue>-<issue title>`, e.g. 57-export-energy-costs-as-csv'
HOTFIX_NEXT = 'the maintainer in charge merges it or opens a PR as they see fit'


def submit(ctx, title=None, desc=None, finished=False):
    candidate, config, model = ctx.candidate, ctx.config, ctx.model
    branch = checkouts.current_branch(candidate)
    require(branch, 'the candidate has a detached HEAD; switch to a branch first')
    require(branch not in model.names, f'never on {branch}, a listed {model.level(branch)} branch: work on the branch '
            f'of the work-order issue ({ISSUE_BRANCH_HINT}; `factory start workorder <issue>` creates it)')
    name = model.config_branch
    with ctx.candidate_lock():
        tips = checkouts.fetch(candidate, config, name, branch)
        require(name in tips, f'the config branch {name} is not on GitHub')
        policy, remote = tips[name], tips.get(branch)
        order = workorders.branch_order(branch, workorders.names_on(candidate, policy))
        hotfix = workorders.is_hotfix_branch(branch)
        if hotfix:
            require(not finished, f'{branch} is a hotfix without a work order, so --finished opens no PR from it: '
                    f'{HOTFIX_NEXT}')
        elif not order:
            require(not finished, f'{branch} belongs to no work order, so --finished opens no PR from it '
                    f'({ISSUE_BRANCH_HINT})')
            common.countdown(f'{branch} belongs to no work order ({ISSUE_BRANCH_HINT}); this commit and push are not '
                             'tied to any work order')
        local = checkouts.head(candidate)
        if remote:
            require(is_ancestor(candidate, remote, local), f'{branch} is behind or diverged from GitHub; run '
                    f'`git -C {candidate} pull --ff-only` (or merge) first')
        staged = git(candidate, 'diff', '--cached', '--quiet', check=False).returncode == 1
        if staged:
            heading = title or (workorders.heading(order, read_order(ctx, policy, order)[0]) if order else None)
            if heading:
                git(candidate, 'commit', '--quiet', '-m', heading, *(['-m', desc] if desc else []))
            else:
                common.git(candidate, 'commit', interactive=True, env={'GIT_EDITOR': editor_command()})
            local = checkouts.head(candidate)
            say(f'Committed {local[:12]} on {branch}.')
        if remote != local:
            git(candidate, 'push', '--quiet', checkouts.github_url(config), f'HEAD:refs/heads/{branch}', network=True)
            git(candidate, 'config', f'branch.{branch}.remote', 'origin')
            git(candidate, 'config', f'branch.{branch}.merge', f'refs/heads/{branch}')
            git(candidate, 'update-ref', f'refs/remotes/origin/{branch}', local)
            say(f'Pushed {branch} ({local[:12]}).')
        elif not staged:
            say('Nothing staged and nothing new to push.')
    if not finished:
        if order:
            say('When the work order is done: `factory submit --finished`.')
        elif hotfix:
            say(f'{branch} is a hotfix without a work order: {HOTFIX_NEXT}')
        return 0
    task = workorders.task_of(order)
    text, spec = read_order(ctx, policy, order)
    pull = open_pull_for(ctx, branch)
    # An open PR keeps its target; a new one goes to the validation branch routed for the work order's kind.
    target = pull['base']['ref'] if pull else model.route(spec['kind'])
    tip = ctx.tip(target)
    require(is_ancestor(candidate, tip, local), f'{branch} does not contain current {target}. Run '
            f'`git -C {candidate} merge origin/{target}`, resolve conflicts, then `factory submit --finished` again '
            '(for an open PR, `gh pr update-branch <n>` merges it on GitHub)')
    imports = checkouts.direct_imports(candidate, tip, local)
    if pull:
        return finish_open_pr(ctx, pull, local, branch, task, imports)
    # Said only once the PR exists: a preflight that does not pass opens none.
    label = workorders.label(order)
    closes = (lambda number: say(f'PR #{number} says `Closes {label}`: GitHub closes the issue when it merges into its '
                                 'default branch.')) if workorders.is_issue(order) else None
    heading = title or workorders.heading(order, text)
    commits = out(candidate, 'log', '--format=- %s', f'{tip}..{local}')
    with checkouts.scratch('submit-') as scratch:
        body = scratch / 'body.md'
        body.write_text((desc.strip() + '\n\n' if desc else '') + f'{workorders.work_order_line(order)}\n\n'
                        f'Commits:\n{commits}\n')
        common.keep_awake()  # session.py submit watches the new PR's review
        with checkouts.candidate_snapshot(candidate, ctx.control, local, branch, config) as snapshot:
            created = session_submit(ctx, snapshot, task, heading, body, imports, on_created=closes, base=target)
    return 0 if created else 1


# --- watch, merge ------------------------------------------------------------------------------------

def session_watch(policy, pr, *args):
    """Streamed rather than captured, so the maintainer follows a long review as it runs; a stale `/review` is
    reported in plain words instead of waited on."""
    command = checkouts.tool_command(policy, 'session.py', 'watch', '--pr', pr, *args)
    process = subprocess.Popen(command, cwd=policy, env=checkouts.tool_env(), stdout=subprocess.PIPE, text=True)
    lines = []
    try:
        for line in process.stdout:
            say(common.printable(line.rstrip('\n'), 20000))
            lines.append(line)
        code = process.wait()
    except KeyboardInterrupt:
        checkouts.settle(process)
        raise
    finally:
        process.stdout.close()
    result = checkouts.last_json(''.join(lines)) or {}
    if result.get('status') == 'stale':
        warn(f'PR #{pr}: ' + common.printable(result.get('message') or 'the pending review is stale', 500))
    return code


def watch(ctx, pr=None, everything=False):
    common.keep_awake()  # the binding review runs on this device while it watches
    if not everything:
        with checkouts.policy_checkout(ctx.control, ctx.policy, ctx.config) as policy:
            return session_watch(policy, pr)
    say(f'Reviewing every PR labelled awaiting-senior-review every {WATCH_ALL_INTERVAL} s; Ctrl-C stops.')
    while True:
        with common.Lock(common.STATE_DIR / 'locks/control.lock', 'the control checkout'):
            _, changed = checkouts.update_control(ctx.control, ctx.config, branch=ctx.branch)
            current = checkouts.read_policy(ctx.control, ctx.config)
        if changed:
            ctx.reexec(fresh=True)
        waiting = ctx.gh.pages(f"/repos/{ctx.config['repository']}/issues?state=open&labels=awaiting-senior-review")
        with checkouts.policy_checkout(ctx.control, current.tip, ctx.config) as policy:
            for item in waiting:
                if item.get('pull_request'):
                    say(f'PR #{item["number"]}: {common.printable(item.get("title", ""), 200)}')
                    session_watch(policy, item['number'], '--once')  # a stale or failed PR never stops the others
        time.sleep(WATCH_ALL_INTERVAL)


def merge(ctx, pr, dry_run=False):
    """session.py merge takes the target from the PR (validation branches only; production PRs merge on GitHub)."""
    with checkouts.policy_checkout(ctx.control, ctx.policy, ctx.config) as policy:
        code, _, _ = checkouts.run_tool(policy, 'session.py', 'merge', '--pr', pr, *(['--dry-run'] if dry_run else []))
    if code == 0 and not dry_run:
        pull = ctx.gh.request('GET', f"/repos/{ctx.config['repository']}/pulls/{int(pr)}")
        target = (pull.get('base') or {}).get('ref')
        require(target in ctx.model.names, f'pull request #{pr} targets an unlisted branch')
        ctx.tips(target)
        say(f'Merged. Update your branches from origin/{target} when you continue.')
    return code


# --- doctor ------------------------------------------------------------------------------------------

def tools_command(control, destination, names):
    """(command, tools) installing those of `names` that factory/tools.lock.json pins into `destination`, with the
    control checkout's reviewed installer (release binaries, SHA-256 checked); None when it pins none of them."""
    lock = Path(control) / 'factory/tools.lock.json'
    try:
        locked = [name for name in names if name in json.loads(lock.read_text())]
    except (OSError, ValueError):
        return None
    if not locked:
        return None
    return shlex.join(['python3', '-I', '-B', str(Path(control) / 'factory/install_tools.py'), '--lock', str(lock),
                       '--destination', str(destination), *[part for name in locked for part in ('--only', name)]]), locked


def doctor_report(report, keychain=(), install=None):
    """doctor.py's status, then each of its blocked checks with its fix. Its environment check of an author key is
    expected to block when that key is in the keychain: factory hands it to each author run, never to doctor.py.
    install(names) returns (one command, the tools it installs) for the missing tools, or None."""
    if not report:
        return ['doctor.py: produced no report']
    blocked = [item for item in report.get('factory', {}).get('local_prerequisites', []) if item.get('status') == 'blocked']
    lines = [f'doctor.py: {report.get("status", "unknown")}' + ('' if blocked or report.get('reason') else '; no blocked checks')]
    if report.get('reason'):
        lines.append(f'  {report["reason"]}')
    tools = [str(item.get('check'))[len('tool_'):] for item in blocked if str(item.get('check')).startswith('tool_')]
    command, covered = (install(tools) if install and tools else None) or (None, ())
    for item in blocked:
        name = str(item.get('check') or '?')
        if name.startswith('environment_') and name[len('environment_'):] in keychain:
            lines.append(f'  expected {name}: the key is in the keychain; doctor.py sees only exported keys')
        elif name.startswith('tool_') and name[len('tool_'):] in covered:
            lines.append(f'  blocked  {name}  → installed by the command below')
        else:
            lines.append(f'  blocked  {name}  → {item.get("continuation") or item.get("detail") or "see doctor.py"}')
    if command:
        lines.append(f'  install the missing check tools: {command}')
    return lines


def doctor(ctx):
    import clients
    checks = []

    def check(name, ok, fix=''):
        checks.append((name, bool(ok), fix))

    shim = ctx.device['bin'] / 'factory'
    found = common.tool('factory', required=False)
    check('shim on PATH', found and Path(found).resolve() == shim.resolve(),
          f'open a new terminal or add {ctx.device["bin"]} to PATH (installer)')
    check('control and candidate are separate', _quiet(checkouts.separate, ctx.control, ctx.candidate))
    check('candidate checkout', _quiet(checkouts.verify_candidate, ctx.candidate, ctx.config), 'see the message of any factory command')
    for service, name in (('aicepeak-factory-anthropic-api-key', 'ANTHROPIC_API_KEY'),
                          ('aicepeak-factory-context7-api-key', 'CONTEXT7_API_KEY')):
        check(f'author key {name}', os.environ.get(name) or keychain_present(service),
              'rerun the installer with --author-keys, or export it')
    _, problem = common.wait_for_docker(clients.IMAGE)
    check('Docker running', problem != 'docker', f'no answer within {common.DOCKER_WAIT} s, not even after starting Docker '
          'Desktop: check that it is installed (docs/dev-setup.md)')
    check('author image', problem is None, f'docker build -f {ctx.control}/factory/Dockerfile -t {clients.IMAGE} '
          f'{ctx.control}/factory' if problem == 'image' else 'needs Docker running (above)')
    codex = common.tool('codex', required=False)
    version = subprocess.run([codex, '--version'], capture_output=True, text=True).stdout.strip() if codex else ''
    check(f'pinned Codex ({clients.VERSIONS["codex"]})', version == clients.VERSIONS['codex'],
          f'found {version or "none"}; install the version factory/package.json pins: docs/dev-setup.md step 2')
    check('gh maintainer login', _quiet(checkouts.maintainer, ctx.gh, ctx.config), 'gh auth login; see docs/dev-setup.md')
    for name, ok, fix in checks:
        say(f'{"ok  " if ok else "FAIL"} {name}' + ('' if ok else f'  → {fix}'))
    with checkouts.policy_checkout(ctx.control, ctx.policy, ctx.config) as policy:
        code, stdout, _ = checkouts.run_tool(policy, 'doctor.py', '--root', policy, '--runner', ctx.config['runners'][0],
                                            capture=True)
    report = checkouts.last_json(stdout) or {}
    keychain = {name.split()[-1] for name, ok, _ in checks if ok and name.startswith('author key ')}
    for line in doctor_report(report, keychain, lambda names: tools_command(ctx.control, ctx.device['bin'], names)):
        say(line)
    say('(doctor.py always exits 2: it never certifies live acceptance.)')
    return 0 if all(ok for _, ok, _ in checks) else 1


def _quiet(function, *args):
    try:
        function(*args)
        return True
    except (Blocked, OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def keychain_present(service):
    security = common.tool('security', required=False)
    return bool(security) and subprocess.run([security, 'find-generic-password', '-s', service],
                                             capture_output=True).returncode == 0
