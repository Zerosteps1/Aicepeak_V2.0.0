"""Foreground factory commands: issue, submit workorders, submit, watch, merge and doctor."""
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
import issues
import workorders

WATCH_ALL_INTERVAL = 60
VERBS = {'add': 'add', 'edit': 'update', 'delete': 'remove'}
def approvals(model):
    """What a work-order or config PR needs next: work_order_approvals maintainers, then a merge on GitHub."""
    needed = model.work_order_approvals
    return (f'Next: {needed} maintainer{"" if needed == 1 else "s"} other than its author approve{"s" if needed == 1 else ""} '
            'the pull request at its current head; a maintainer merges it on GitHub (`factory merge` never merges into a '
            'production branch).')


def open_editor(path):
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    if editor:
        subprocess.run([*shlex.split(editor), str(path)], check=False)
    elif sys.platform == 'darwin' and common.tool('open', required=False):
        subprocess.run([common.tool('open'), '-t', str(path)], check=False)
    else:
        say(f'Open {path} in your editor.')


def editor_command():
    return os.environ.get('VISUAL') or os.environ.get('EDITOR') or 'vi'


# --- issue -----------------------------------------------------------------------------------------

TITLE_PLACEHOLDER = 'Short outcome-oriented title'


def draft_title(text):
    """Title and body of an edited draft: the first line is `# <title>`."""
    first, _, body = text.partition('\n')
    require(first.startswith('# '), 'the first line of the draft must be "# <title>"')
    return first[2:].strip(), body.lstrip('\n')


def issue(ctx, title=None, kind='factory', noedit=False):
    """A new work-order issue under the maintainer's own gh login; the factory never creates issues itself."""
    body = workorders.issue_body((ctx.root / workorders.ISSUE_TEMPLATE).read_text(), kind)
    if noedit:
        require(title and title.strip(), '--noedit needs --title')
        title = title.strip()
    else:
        draft = common.STATE_DIR / 'tmp' / f'issue-draft-{os.getpid()}.md'
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(f'# {title or TITLE_PLACEHOLDER}\n\n{body}')
        say(f'Write the work order in {editor_command()}; save and close the editor to continue.')
        subprocess.run([*shlex.split(editor_command()), str(draft)], check=False)
        title, body = draft_title(draft.read_text())
        require(common.ask(f'Create the work-order issue "{common.printable(title, 200)}" on GitHub?'),
                f'nothing created; your draft stays in {draft}')
        draft.unlink()
    require(title and title != TITLE_PLACEHOLDER and len(title) <= 256, 'the issue needs a title (at most 256 characters)')
    spec = issues.draft_spec(body)
    created = ctx.gh.request('POST', f"/repos/{ctx.config['repository']}/issues", {'title': title, 'body': body})
    say(f"Created work-order issue #{created['number']}: {created['html_url']}")
    if spec['kind'] == 'product' and not ctx.config.get('product_checks_ready'):
        warn('product work orders stay blocked until product_checks_ready is true in factory/config.json')
    say('Next: fill in or check goal, non-goals, acceptance criteria and verification on GitHub, then comment `/review` '
        'on the issue. The factory proposes allowed_paths and section fixes; `/accept` applies the paths and approves it. '
        f"Then `factory start workorder {created['number']}`.")
    return 0


# --- submit workorders -------------------------------------------------------------------------------

def collect_orders(candidate):
    """Uncommitted work-order changes against the candidate's HEAD: new files, edits and deletions."""
    changes = {}
    raw = git(candidate, 'diff', '--name-status', '--no-renames', '-z', 'HEAD', '--', workorders.WORK).stdout.split(b'\0')
    for status, path in zip(raw[0::2], raw[1::2]):
        path = path.decode('utf-8')
        if workorders.is_order(path):
            changes[path] = None if status == b'D' else common.read_regular(candidate, path)
    for path in out(candidate, 'ls-files', '--others', '--exclude-standard', '-z', '--', workorders.WORK).split('\0'):
        if path and workorders.is_order(path):
            changes[path] = common.read_regular(candidate, path)
    return changes


def blob(repo, sha, path):
    result = git(repo, 'cat-file', 'blob', f'{sha}:{path}', check=False)
    return result.stdout if result.returncode == 0 else None


def show_diff(path, before, after):
    lines = difflib.unified_diff((before or b'').decode('utf-8', 'replace').splitlines(),
                                 (after or b'').decode('utf-8', 'replace').splitlines(),
                                 f'a/{path}', f'b/{path}', lineterm='')
    say(common.printable('\n'.join(lines), 20000))


def submit_workorders(ctx):
    """Work orders live on the config branch: their PR goes there (type b), so numbers stay unique."""
    candidate, config, gh = ctx.candidate, ctx.config, ctx.gh
    name = ctx.model.config_branch
    branch = f'{ctx.login}/new-workorders'
    require(checkouts.current_branch(candidate) != branch,
            f'the candidate is on {branch}: commit there with `factory submit --workorder FACTORY-001`, or switch branches')
    with ctx.candidate_lock():
        tips = checkouts.fetch(candidate, config, name, branch)
        require(name in tips, f'the config branch {name} is not on GitHub')
        policy, tip, head = tips[name], tips.get(branch), checkouts.head(candidate)
        changes = collect_orders(candidate)
    require(changes, 'no uncommitted work-order changes in docs/work/ (new files, edits or deletions)')
    pulls = workorders.open_pulls(gh, config)
    own = [pull for pull in pulls if pull['head']['ref'] == branch]
    replace = None
    if own:
        base, pull = own[0]['head']['sha'], own[0]
        require(base == tip, f'pull request #{pull["number"]} moved while fetching; retry')
        target = (pull.get('base') or {}).get('ref')
        require(target == name, f'pull request #{pull["number"]} of {branch} targets {target}, not the config branch '
                f'{name}; close it, then submit again')
    elif tip and not is_ancestor(candidate, tip, policy):
        say(f'Branch {branch} has commits that are not on {name} and no open pull request:')
        say(common.printable(out(candidate, 'log', '--oneline', f'{policy}..{tip}'), 4000))
        require(common.ask(f'Replace {branch} with this submission?'), 'nothing submitted')
        base, pull, replace = policy, None, tip
    else:
        base, pull = policy, None
    other = [p for p in pulls if p['head']['ref'] != branch]
    used = workorders.numbers_ever_added(candidate, policy) | workorders.numbers_in_pulls(gh, config, other)
    errors, kinds = [], {}
    for path, data in sorted(changes.items()):
        in_head, in_base = blob(candidate, head, path), blob(candidate, base, path)
        if in_head is not None and in_base != in_head and not (own and in_base is not None):
            errors.append(f'{path}: changed on {name} since your branch; update the candidate first (merge origin/{name})')
        new = data is not None and in_base is None
        if data is None:
            kinds[path] = 'delete'
            if in_base is None:
                errors.append(f'{path}: not present on {"the pull request" if own else name}; nothing to delete')
            continue
        kinds[path] = 'add' if new else 'edit'
        errors += workorders.problems(path, data.decode('utf-8', 'replace'), new=new,
                                      used_numbers=used if new else set())
        if new and workorders.number(workorders.name_of(path)) is not None:
            used = used | {workorders.number(workorders.name_of(path))}  # one counter, also within one submission
    require(not errors, 'work orders not submitted:\n  ' + '\n  '.join(errors))
    for path, data in sorted(changes.items()):
        if kinds[path] == 'delete':
            require(common.ask(f'Delete {path} on {name}?'), 'nothing submitted')
        elif kinds[path] == 'edit':
            show_diff(path, blob(candidate, base, path), data)
            require(common.ask(f'Submit this change to {path}?'), 'nothing submitted')
    for path, data in sorted(changes.items()):
        if data is not None and workorders.task_block(data.decode())['status'] != 'approved':
            if common.ask(f'{path} is still a draft. Approve it now (status "approved")?'):
                data = workorders.set_status(data.decode(), 'approved').encode()
                common.replace_file(candidate, path, data)
                changes[path] = data
            else:
                warn(f'{path} is submitted as a draft; it authorizes nothing until approved and merged')
    summary = ', '.join(f'{VERBS[kinds[p]]} {workorders.name_of(p)}' for p in sorted(changes))
    message = ('docs(work): ' + summary) if len(summary) <= 60 else f'docs(work): {len(changes)} work orders'
    with checkouts.scratch('workorders-') as scratch:
        repo = checkouts.materialize(scratch / 'repo', base, origin=checkouts.github_url(config), branch=branch,
                                     objects=[checkouts.objects_dir(candidate), checkouts.objects_dir(ctx.control)])
        identity = ctx.identity()
        if not is_ancestor(repo, policy, base):
            merged = git(repo, *identity, 'merge', '--no-edit', '--quiet', policy, check=False)
            require(merged.returncode == 0, f'pull request #{pull["number"]} conflicts with {name}; resolve it on its branch first')
        for path, data in changes.items():
            if data is None:
                git(repo, 'rm', '--quiet', '--', path)
            else:
                target = common.checked_target(repo, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                git(repo, 'add', '--', path)
        git(repo, *identity, 'commit', '--quiet', '-m', message)
        sha = checkouts.head(repo)
        lease = [f'--force-with-lease=refs/heads/{branch}:{replace}'] if replace else []
        git(repo, 'push', '--quiet', *lease, checkouts.github_url(config), f'HEAD:refs/heads/{branch}', network=True)
        say(f'Pushed {len(changes)} work order change(s) to {branch} ({sha[:12]}).')
        with ctx.candidate_lock():
            checkouts.fetch(candidate, config, branch)  # later snapshots of this commit read the candidate's objects
        if pull:
            say(f'Updated pull request #{pull["number"]}: {pull["html_url"]}')
        else:
            body = scratch / 'body.md'
            body.write_text('Work orders submitted with `factory submit workorders`:\n\n' + '\n'.join(
                f'- {kinds[p]}: `{p}`' + ('' if changes[p] is None else f' – {workorders.title_of(changes[p].decode())}')
                for p in sorted(changes)) + '\n')
            # No advisory preflight: maintainer approvals and factory/deterministic decide work-order PRs.
            created = session_submit(ctx, repo, None, message, body, base=name,
                                     on_created=lambda _: move_out(candidate, head, changes))
            if created:
                say(approvals(ctx.model) + ' After the merge, bring them into your branch: `factory update`.')
    if pull:
        move_out(candidate, head, changes)
        return finish_open_pr(ctx, pull, sha, branch, None, [])
    return 0 if created else 1


def move_out(candidate, head, changes):
    """Submitted changes now live on the work-order branch; only byte-identical files leave the working tree."""
    moved = []
    for path, data in changes.items():
        original = blob(candidate, head, path)
        target = common.checked_target(candidate, path)
        current = target.read_bytes() if target.is_file() else None
        if current != data:
            continue
        if original is None:
            common.remove_file(candidate, path)
        else:
            common.replace_file(candidate, path, original)
        git(candidate, 'reset', '--quiet', 'HEAD', '--', path)  # nor may a staged copy stay behind
        moved.append(path)
    if moved:
        say('Moved out of your working tree (they now live on the work-order branch): ' + ', '.join(moved))


# --- submit ------------------------------------------------------------------------------------------

def run_session_submit(ctx, snapshot, args, on_created=None):
    """Run session.py submit; on_created runs as soon as the PR line is printed, before the watch."""
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


def session_submit(ctx, snapshot, task, title, body_file, context=(), draft=False, on_created=None, *, base):
    """session.py submit into base: a validation branch, or a production branch for work-order and config PRs. Without
    a task (work-order and config PRs) there is no advisory preflight: maintainer approvals and
    factory/deterministic decide."""
    args = [*(['--task', task] if task else []), '--base', base, '--runner', ctx.config['runners'][0], '--title', title,
            '--body-file', body_file]
    for path in context:
        args += ['--context', path]
    if draft:
        args.append('--draft')
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
    """An existing PR: a draft becomes ready after a passing preflight (none without a task: work-order and config
    PRs); then this device watches a PR into a validation branch."""
    number = pull['number']
    if pull.get('draft') and task:
        with checkouts.candidate_snapshot(ctx.candidate, ctx.control, sha, branch, ctx.config) as snapshot:
            review = preflight(ctx, snapshot, task, context, base=pull['base']['ref'])
        describe_review(review)
        if review['outcome'] != 'pass':
            say(f'Pull request #{number} stays a draft; fix the findings and run `factory submit --finished` again.')
            return 1
    if pull.get('draft'):
        ctx.gh.command(['pr', 'ready', str(number), '--repo', ctx.config['repository']])
        say(f'Pull request #{number} is ready for review.')
    if ctx.model.level(pull['base']['ref']) == 'production':  # type b: no senior review to watch for
        say(approvals(ctx.model))
        return 0
    say(f'Watching pull request #{number}; Ctrl-C stops watching (the PR keeps waiting for a watcher).')
    return watch(ctx, number)


def submit(ctx, title=None, desc=None, finished=False, draft=False, workorder=None, context=()):
    candidate, config, model = ctx.candidate, ctx.config, ctx.model
    branch = checkouts.current_branch(candidate)
    require(branch, 'the candidate has a detached HEAD; switch to a branch first')
    require(branch not in model.names, f'never on {branch}, a listed {model.level(branch)} branch: create a feature '
            f'branch first, e.g. `git -C {candidate} switch -c {ctx.login}/<ID>`')
    name = model.config_branch
    with ctx.candidate_lock():
        tips = checkouts.fetch(candidate, config, name, branch)
        require(name in tips, f'the config branch {name} is not on GitHub')
        policy, remote = tips[name], tips.get(branch)
        names = workorders.names_on(candidate, policy)
        order = workorders.resolve(workorder, names) if workorder else workorders.branch_order(branch, names)
        if not order:
            require(not finished, f'{branch} belongs to no work order; pass --workorder <n> with --finished')
            common.countdown(f'{branch} belongs to no work order (expected <login>/<ID>); '
                             'this commit and push are not tied to any work order')
        local = checkouts.head(candidate)
        if remote:
            require(is_ancestor(candidate, remote, local), f'{branch} is behind or diverged from GitHub; run '
                    f'`git -C {candidate} pull --ff-only` (or merge) first')
        staged = git(candidate, 'diff', '--cached', '--quiet', check=False).returncode == 1
        if staged:
            heading = title or (f'{workorders.label(order)}: '
                                f'{workorders.title_of(workorders.read(ctx.gh, candidate, config, policy, order)[0])}' if order else None)
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
        return 0
    task = workorders.task_of(order)
    text, spec = workorders.read(ctx.gh, candidate, config, policy, order)
    pull = open_pull_for(ctx, branch)
    # An open PR keeps its target; a new one goes to the validation branch routed for the work order's kind.
    target = pull['base']['ref'] if pull else model.route(spec['kind'])
    tip = ctx.tip(target)
    require(is_ancestor(candidate, tip, local), f'{branch} does not contain current {target}. Run '
            f'`git -C {candidate} merge origin/{target}`, resolve conflicts, then `factory submit --finished` again '
            '(for an open PR, `gh pr update-branch <n>` merges it on GitHub)')
    imports = list(dict.fromkeys([*checkouts.direct_imports(candidate, tip, local), *context]))
    if pull:
        if draft:
            warn(f'--draft is ignored: pull request #{pull["number"]} already exists')
        return finish_open_pr(ctx, pull, local, branch, task, imports)
    heading = title or f'{workorders.label(order)}: {workorders.title_of(text)}'
    commits = out(candidate, 'log', '--format=- %s', f'{tip}..{local}')
    with checkouts.scratch('submit-') as scratch:
        body = scratch / 'body.md'
        # An issue reference links the PR into the work-order issue's timeline.
        reference = task if workorders.is_issue(order) else f'`{task}`'
        body.write_text((desc.strip() + '\n\n' if desc else '') + f'Work order: {reference}\n\nCommits:\n{commits}\n')
        with checkouts.candidate_snapshot(candidate, ctx.control, local, branch, config) as snapshot:
            created = session_submit(ctx, snapshot, task, heading, body, imports, draft, base=target)
    return 0 if created else 1


# --- watch, merge ------------------------------------------------------------------------------------

def session_watch(policy, pr, *args):
    """session.py watch with its output streamed as it comes; a stale `/review` is said in plain words, not waited on."""
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
    check('author image', problem is None, f'docker build -f {ctx.control}/factory/Dockerfile -t {clients.IMAGE} {ctx.control}/factory'
          if problem == 'image' else 'needs Docker running (above)')
    codex = common.tool('codex', required=False)
    version = subprocess.run([codex, '--version'], capture_output=True, text=True).stdout.strip() if codex else ''
    check('pinned Codex 0.164.0', version == 'codex-cli 0.164.0', 'docs/dev-setup.md step 2')
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
