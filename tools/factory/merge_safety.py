"""Merge safety for parallel pull requests: a read-only collision sweep and a verified human merge.

Like session.py, both run from the clean control checkout on a maintainer host and never execute
candidate code; `merge` acts with the maintainer's own gh login. Models never merge.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import engine
import session  # attributes are read at call time, so either module may be imported first
from contracts import Blocked, handoff, require



def object_store(root):
    common = session.git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip()
    return str(Path(common) / 'objects')


def trial_git(trial, *args, protocols='', timeout=30):
    # Alternate refs would run Git inside the candidate with its own config; commit-graphs
    # and background maintenance stay off too. A timeout is an unknown result, not a block.
    try:
        return session.git_run(trial, '-c', 'core.alternateRefsCommand=true', '-c', 'core.commitGraph=false',
                       '-c', 'maintenance.auto=false', '-c', 'gc.auto=0', *args, protocols=protocols, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(args, 128, b'', b'')


def fetch_pulls(trial, numbers):
    """Fetch other PR heads into the scratch repository only; no candidate configuration takes part."""
    refspecs = [f'+refs/pull/{number}/head:refs/factory/pull/{number}' for number in numbers]
    result = trial_git(trial, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head',
                       f'https://github.com/{session.REPOSITORY}.git', *refspecs, protocols='https', timeout=120)
    return result.returncode == 0


def conflicts(trial, ours, theirs):
    """Files a merge of theirs into ours would conflict in; None when Git cannot tell."""
    result = trial_git(trial, 'merge-tree', '--write-tree', '--name-only', '--no-messages', '-z', ours, theirs)
    fields = result.stdout.split(b'\0')
    if result.returncode not in (0, 1) or not re.fullmatch(rb'[0-9a-f]{40}\n?', fields[0]):
        return None
    names = sorted({name.decode('utf-8') for name in fields[1:] if name})
    # Exit 1 without a file (a directory-rename split) is a conflict Git does not name.
    return (names or None) if result.returncode else []


def collisions(gh, candidate, task=None):
    """Read-only sweep of the committed candidate against current main and the other open PRs."""
    config, policy, _ = session.control(gh)
    candidate = Path(candidate).resolve()
    require(candidate != session.ROOT.resolve(), 'use a separate candidate checkout')
    sha = session.identity(candidate, config)
    branch = session.git(candidate, 'symbolic-ref', '--quiet', '--short', 'HEAD').decode().strip()
    require(branch and branch != config['default_branch'], 'candidate must be on a feature branch')
    if task is not None:
        session.task_order(config, policy, task)
    limitations, others = [], []
    with tempfile.TemporaryDirectory(prefix='factory-collisions-') as directory:
        trial = Path(directory) / 'trial.git'
        session.git(Path(directory), 'init', '--quiet', '--bare', '--template=', str(trial))
        # Read candidate and control objects in place; every write lands in this scratch repository.
        (trial / 'objects/info/alternates').write_text(object_store(session.ROOT) + '\n' + object_store(candidate) + '\n')
        # Local refs let the fetch send what it already has instead of downloading everything.
        for name, value in (('main', policy), ('candidate', sha)):
            require(trial_git(trial, 'update-ref', 'refs/factory/' + name, value).returncode == 0,
                    'candidate or current main objects missing; fetch them fully')
        found = trial_git(trial, 'merge-base', policy, sha)
        require(found.returncode == 0, 'candidate shares no complete history with current main; fetch it fully')
        base = found.stdout.decode().strip()
        main = {'sha': policy, 'contains': base == policy, 'conflicts': [] if base == policy else conflicts(trial, sha, policy)}
        if main['conflicts'] is None:
            limitations.append('Trial merge with current main failed; its conflicts are unknown.')
        listed = trial_git(trial, 'diff-tree', '--no-commit-id', '--no-renames', '--name-only', '-r', '-z', base, sha)
        require(listed.returncode == 0, 'candidate objects missing; fetch them fully')
        changed = {name.decode('utf-8') for name in listed.stdout.split(b'\0') if name}
        for pr in gh.pages(f'/repos/{session.REPOSITORY}/pulls?state=open&base={config["default_branch"]}'):
            if (pr['head'].get('repo') or {}).get('full_name') != session.REPOSITORY:
                continue  # forks are unsupported by the factory and cannot block the sweep
            if pr['head']['ref'] == branch:
                continue  # the candidate's own PR
            try:
                files = gh.pages(f'/repos/{session.REPOSITORY}/pulls/{pr["number"]}/files')
            except Blocked:
                limitations.append(f"#{pr['number']}: its file list could not be read; overlap unknown.")
                continue
            touched = {f['filename'] for f in files} | {f['previous_filename'] for f in files if f.get('previous_filename')}
            try:
                other_task = handoff(pr.get('body'), config)['task']
            except (Blocked, TypeError, ValueError, KeyError):
                other_task = None
            same = task is not None and other_task == task
            if same or changed & touched:
                others.append({'pr': pr['number'], 'draft': pr['draft'], 'head_sha': pr['head']['sha'], 'same_task': same,
                               'overlap': sorted(changed & touched), 'conflicts': None})
        if others and not fetch_pulls(trial, [other['pr'] for other in others]):
            limitations.append('Could not fetch the overlapping PR heads; their trial merges did not run.')
        elif others:
            for other in others:
                ref = trial_git(trial, 'rev-parse', '--verify', '--quiet', f"refs/factory/pull/{other['pr']}^{{commit}}")
                if ref.returncode or ref.stdout.decode().strip() != other['head_sha']:
                    limitations.append(f"#{other['pr']} changed during the sweep; its trial merge was skipped.")
                    continue
                other['conflicts'] = conflicts(trial, sha, other['head_sha'])
                if other['conflicts'] is None:
                    limitations.append(f"Trial merge with #{other['pr']} failed; its conflicts are unknown.")
    return {'candidate': {'branch': branch, 'head_sha': sha, 'task': task}, 'main': main,
            'open_prs': others, 'limitations': limitations}


def collision_summary(report):
    """Bounded Markdown for the PR body; PR numbers create cross-references, not comments."""
    def names(items):
        return ', '.join(f'`{n}`' for n in items[:10]) + (f' and {len(items) - 10} more' if len(items) > 10 else '')
    main = report['main']
    state = ('contains current main' if main['contains'] else 'does NOT contain current main; '
             + ('conflicts in ' + names(main['conflicts']) if main['conflicts'] else 'merge it in'))
    lines = [f"Collision check at `{report['candidate']['head_sha'][:12]}` against main `{main['sha'][:12]}`: {state}."]
    for other in report['open_prs'][:20]:
        merge = ('trial merge not run' if other['conflicts'] is None else 'trial merge clean' if not other['conflicts']
                 else 'trial merge conflicts in ' + names(other['conflicts']))
        lines.append(f"- #{other['pr']}{' (same work order)' if other['same_task'] else ''}: "
                     f"overlapping files {names(other['overlap']) or 'none'}; {merge}.")
    if report['open_prs']:
        lines.append('Merge one PR at a time. The PR merged second updates its branch and resolves its own conflicts '
                     'with main; nothing is resolved against unmerged PRs.')
    else:
        lines.append('No other open PR touches the same files or work order.')
    lines += ['Limitation: ' + item for item in report['limitations'][:10]]
    return '\n'.join(lines)[:6000]


def unresolved_threads(gh, pr):
    owner, name = session.REPOSITORY.split('/')
    query = ('query($owner:String!,$name:String!,$pr:Int!){repository(owner:$owner,name:$name){'
             'pullRequest(number:$pr){reviewThreads(first:100){totalCount nodes{isResolved}}}}}')
    data = json.loads(gh.command(['api', 'graphql', '-f', 'query=' + query, '-f', 'owner=' + owner,
                                  '-f', 'name=' + name, '-F', f'pr={pr}']))
    threads = data['data']['repository']['pullRequest']['reviewThreads']
    require(threads['totalCount'] == len(threads['nodes']), 'review threads incomplete; check them on GitHub')
    return sum(not node['isResolved'] for node in threads['nodes'])


MERGE_LOCK = 'tags/factory-merge-lock'


def merge(gh, pr, dry_run=False):
    """Human merge of exactly the verified head onto exactly the verified main; never run by a model."""
    config, policy, user = session.control(gh)
    snapshot, _, _ = session.pr_state(gh, pr, config, policy)
    head = snapshot['head_sha']
    problems = ['PR is a draft'] if snapshot['draft'] else []
    if not engine.contains_base(gh, session.REPOSITORY, policy, head):
        problems.append(engine.BEHIND_MAIN)
    runs = gh.pages(f'/repos/{session.REPOSITORY}/commits/{head}/check-runs?filter=all', 'check_runs')
    for name in config['required_checks']:
        latest = max((c for c in runs if c.get('name') == name and (c.get('app') or {}).get('id') == config['publisher_app_id']),
                     key=lambda c: c['id'], default=None)
        if latest is None:
            problems.append(name + ': missing from the publisher App')
        elif (latest.get('status'), latest.get('conclusion')) != ('completed', 'success'):
            problems.append(f"{name}: {latest.get('conclusion') or latest.get('status')}")
        elif (latest.get('external_id') or '').split(':')[:4] != [session.REPOSITORY, str(pr), head, policy]:
            problems.append(name + ': bound to another head or an older main; wait for the fresh run')
        elif name == 'factory/senior-review':
            bound = engine.receipt(latest).get('snapshot') or {}
            if (bound.get('handoff'), bound.get('feedback_digest')) != (snapshot['handoff'], snapshot['feedback_digest']):
                problems.append(name + ': handoff or human feedback changed after the review; wait for the fresh run')
    unresolved = unresolved_threads(gh, pr)
    if unresolved:
        problems.append(f'{unresolved} unresolved review thread(s)')
    verdict = {'pr': pr, 'head_sha': head, 'main_sha': policy, 'mergeable': not problems, 'problems': problems}
    if dry_run:
        return verdict
    require(not problems, 'not merged: ' + '; '.join(problems))
    # GitHub pins only the head of a merge, never its base: merges through this helper are
    # serialized by a ref that GitHub creates atomically, and re-validated while it is held.
    release = f'gh api -X DELETE repos/{session.REPOSITORY}/git/refs/{MERGE_LOCK}'
    try:
        gh.request('POST', f'/repos/{session.REPOSITORY}/git/refs', {'ref': 'refs/' + MERGE_LOCK, 'sha': policy})
    except Blocked:
        raise Blocked(f'merge lock refs/{MERGE_LOCK} is held or could not be created; nothing was merged. '
                      f'If no merge is running, remove it with: {release}') from None
    released = False
    try:
        current = gh.request('GET', f'/repos/{session.REPOSITORY}/git/ref/heads/main')['object']['sha']
        again, _, _ = session.pr_state(gh, pr, config, policy)
        require(current == policy and not again['draft'] and all(again[k] == snapshot[k] for k in ('head_sha', 'handoff', 'feedback_digest')),
                'main or the PR changed before the merge; nothing was merged')
        try:
            gh.command(['pr', 'merge', str(pr), '--repo', session.REPOSITORY, '--merge', '--admin', '--match-head-commit', head])
        except Blocked:
            raise Blocked(f'GitHub refused the merge (changed head, conflict or permission); inspect PR #{pr}') from None
        merged = gh.request('GET', f'/repos/{session.REPOSITORY}/pulls/{pr}')
        commit = merged.get('merge_commit_sha') or ''
        require(merged.get('merged') is True and re.fullmatch('[0-9a-f]{40}', commit), f'GitHub did not report the merge; inspect PR #{pr}')
        parents = [p['sha'] for p in gh.request('GET', f'/repos/{session.REPOSITORY}/commits/{commit}')['parents']]
    finally:
        try:
            gh.request('DELETE', f'/repos/{session.REPOSITORY}/git/refs/{MERGE_LOCK}')
            released = True
        except Blocked:
            pass
    # With the lock held, only a merge outside this helper (the manual bypass) can change the base.
    exact = parents == [policy, head]
    note = ('both required checks were verified for exactly this head and main' if exact else
            f"WARNING: main was `{(parents or ['unknown'])[0]}` at merge time (a merge outside session.py merge); this combination was never tested")
    gh.request('POST', f'/repos/{session.REPOSITORY}/issues/{pr}/comments', {'body':
               f"Merged by {user['login']} with `session.py merge`: head `{head}` onto main `{policy}` as `{commit}`; {note}."})
    require(exact, f'merged as {commit}, but main moved outside session.py merge; verify main before the next merge')
    require(released, f'merged as {commit}, but the merge lock was not released; remove it with: {release}')
    return {**verdict, 'merged': True, 'merge_commit_sha': commit}
