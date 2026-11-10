"""Merge safety for parallel pull requests: a read-only collision sweep and a verified human merge.

Like session.py, both run from the clean config-branch control checkout on a maintainer host and never
execute candidate code; `merge` acts with the maintainer's own gh login and only into gated validation
branches. Models never merge; maintainers merge production PRs on GitHub.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import branches
import bypass
import engine
import session  # attributes are read at call time, so either module may be imported first
from contracts import REPOSITORY, Blocked, handoff, maintainer, require
from github_api import contains


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


def collisions(gh, candidate, task=None, base=None):
    """Read-only sweep of the committed candidate against the current target tip and the other open PRs into it."""
    config, policy, _ = session.control(gh)
    _, base = session.target(config, policy, base, task, fallback=config['default_branch'], gh=gh)
    candidate = Path(candidate).resolve()
    require(candidate != session.ROOT.resolve(), 'use a separate candidate checkout')
    sha = session.identity(candidate, config)
    branch = session.feature_branch(candidate, config)
    if task is not None:
        session.work_order(config, policy, task, gh)
    tip = session.tip(gh, base)
    limitations, others = [], []
    with tempfile.TemporaryDirectory(prefix='factory-collisions-') as directory:
        trial = Path(directory) / 'trial.git'
        session.git(Path(directory), 'init', '--quiet', '--bare', '--template=', str(trial))
        # Read candidate and control objects in place; every write lands in this scratch repository.
        (trial / 'objects/info/alternates').write_text(object_store(session.ROOT) + '\n' + object_store(candidate) + '\n')
        # Local refs let the fetch send what it already has instead of downloading everything.
        for name, value in (('target', tip), ('candidate', sha)):
            require(trial_git(trial, 'update-ref', 'refs/factory/' + name, value).returncode == 0,
                    f'candidate or current {base} objects missing; fetch them fully')
        found = trial_git(trial, 'merge-base', tip, sha)
        require(found.returncode == 0, f'candidate shares no complete history with current {base}; fetch it fully')
        common = found.stdout.decode().strip()
        target = {'ref': base, 'sha': tip, 'contains': common == tip, 'conflicts': [] if common == tip else conflicts(trial, sha, tip)}
        if target['conflicts'] is None:
            limitations.append(f'Trial merge with current {base} failed; its conflicts are unknown.')
        listed = trial_git(trial, 'diff-tree', '--no-commit-id', '--no-renames', '--name-only', '-r', '-z', common, sha)
        require(listed.returncode == 0, 'candidate objects missing; fetch them fully')
        changed = {name.decode('utf-8') for name in listed.stdout.split(b'\0') if name}
        for pr in gh.pages(f'/repos/{session.REPOSITORY}/pulls?state=open&base={quote(base, safe="")}'):
            if pr['head']['ref'] == branch and (pr['head'].get('repo') or {}).get('full_name') == session.REPOSITORY:
                continue  # the candidate's own PR
            # Disjoint file lists do not prove a clean merge (directory renames), so every open PR,
            # forks included through the base repository's pull refs, gets a trial merge.
            try:
                files = gh.pages(f'/repos/{session.REPOSITORY}/pulls/{pr["number"]}/files')
                touched = {f['filename'] for f in files} | {f['previous_filename'] for f in files if f.get('previous_filename')}
                overlap = sorted(changed & touched)
            except Blocked:
                limitations.append(f"#{pr['number']}: its file list could not be read; overlap unknown.")
                overlap = None
            try:
                other_task = handoff(pr.get('body'), config)['task']
            except (Blocked, TypeError, ValueError, KeyError):
                other_task = None
            others.append({'pr': pr['number'], 'draft': pr['draft'], 'head_sha': pr['head']['sha'],
                           'same_task': task is not None and other_task == task, 'overlap': overlap, 'conflicts': None})
        if len(others) > 40:
            limitations.append(f'{len(others) - 40} more open PRs were not trial-merged.')
        merged_into = others[:40]
        if merged_into and not fetch_pulls(trial, [other['pr'] for other in merged_into]):
            limitations.append('Could not fetch the other open PR heads; their trial merges did not run.')
        elif merged_into:
            for other in merged_into:
                ref = trial_git(trial, 'rev-parse', '--verify', '--quiet', f"refs/factory/pull/{other['pr']}^{{commit}}")
                if ref.returncode or ref.stdout.decode().strip() != other['head_sha']:
                    limitations.append(f"#{other['pr']} changed during the sweep; its trial merge was skipped.")
                    continue
                other['conflicts'] = conflicts(trial, sha, other['head_sha'])
                if other['conflicts'] is None:
                    limitations.append(f"Trial merge with #{other['pr']} failed; its conflicts are unknown.")
    return {'candidate': {'branch': branch, 'head_sha': sha, 'task': task}, 'base': target,
            'open_prs': others, 'limitations': limitations}


def collision_summary(report):
    """Bounded Markdown for the PR body; PR numbers create cross-references, not comments."""
    def names(items):
        return ', '.join(f'`{n}`' for n in items[:10]) + (f' and {len(items) - 10} more' if len(items) > 10 else '')
    target = report['base']
    state = (f"contains current {target['ref']}" if target['contains'] else f"does NOT contain current {target['ref']}; "
             + ('conflicts in ' + names(target['conflicts']) if target['conflicts'] else 'merge it in'))
    lines = [f"Collision check at `{report['candidate']['head_sha'][:12]}` against {target['ref']} `{target['sha'][:12]}`: {state}."]
    quiet = [o for o in report['open_prs'] if o['conflicts'] == [] and o['overlap'] == [] and not o['same_task']]
    for other in [o for o in report['open_prs'] if o not in quiet][:20]:
        merge = ('trial merge not run' if other['conflicts'] is None else 'trial merge clean' if not other['conflicts']
                 else 'trial merge conflicts in ' + names(other['conflicts']))
        files = 'unknown' if other['overlap'] is None else names(other['overlap']) or 'none'
        lines.append(f"- #{other['pr']}{' (same work order)' if other['same_task'] else ''}: overlapping files {files}; {merge}.")
    if quiet:
        lines.append(f'{len(quiet)} further open PR(s) share no file and merge cleanly.')
    if len(quiet) < len(report['open_prs']):
        lines.append('Merge one PR at a time. The PR merged second updates its branch and resolves its own conflicts '
                     f"with {target['ref']}; nothing is resolved against unmerged PRs.")
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


# Only explicit rejections: a 5xx, a generic GraphQL error or silence may still end in a merge.
REFUSED = re.compile(r'HTTP 4[0-9][0-9]|not mergeable|was modified|[Rr]equired status|[Rr]epository rule|[Mm]erge conflict')


def gh_merge(pr, head):
    """'sent', 'refused' (GitHub answered no) or 'unknown' (no answer, so GitHub may still merge)."""
    try:
        result = subprocess.run(['gh', 'pr', 'merge', str(pr), '--repo', session.REPOSITORY, '--merge', '--admin',
                                 '--match-head-commit', head], cwd=session.ROOT, env=session.human_env(),
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
        return 'unknown'
    if result.returncode == 0:
        return 'sent'
    return 'refused' if REFUSED.search(result.stderr or '') else 'unknown'


def bypass_record(check):
    try:
        data = json.loads((check.get('output') or {}).get('text') or '')
    except (TypeError, ValueError):
        return None
    return data['bypass'] if isinstance(data, dict) and 'bypass' in data else None


def authentic_bypass(gh, check, record, config, snapshot):
    """None when a bypass names a configured maintainer (id and login), its comment and a bounded reason, and that
    comment is still the maintainer's unedited `/bypass` on this PR; otherwise why the bypass does not count."""
    record = record if isinstance(record, dict) else {}
    try:
        authentic = bypass.reason(record.get('reason')) == record.get('reason')
    except Blocked:
        authentic = False
    if not (authentic and maintainer({'type': 'User', 'id': record.get('id'), 'login': record.get('login')}, config)
            and type(record.get('comment_id')) is int and record['comment_id'] > 0
            and (check.get('output') or {}).get('title') == f"Bypassed by {record['login']}"):
        return 'bypass without an authentic maintainer receipt'
    # The receipt only names the comment: anyone with write access may edit it later, and a deletion withdraws it.
    try:
        current = bypass.read_bypass(gh, config, snapshot, record['comment_id'])[0]
    except Blocked:
        current = None
    if current is None or (current['id'], current['login']) != (record['id'], record['login']):
        return 'the `/bypass` comment could not be re-read, or was edited or deleted; retry, or post a new `/bypass`'
    return None


def check_problem(gh, runs, name, snapshot, config):
    """None when the latest publisher-App check `name` passed for exactly this PR, head, target branch and
    config tip, normally or by an authentic maintainer bypass; otherwise the reason it does not count."""
    latest = max((c for c in runs if c.get('name') == name and (c.get('app') or {}).get('id') == config['publisher_app_id']),
                 key=lambda c: c['id'], default=None)
    if latest is None:
        return name + ': missing from the publisher App'
    if (latest.get('status'), latest.get('conclusion')) != ('completed', 'success'):
        return f"{name}: {latest.get('conclusion') or latest.get('status')}"
    bound = (latest.get('external_id') or '').split(':')
    if len(bound) != 7 or not all(re.fullmatch('[0-9]+', field) for field in bound[5:]):
        return name + ': malformed binding; wait for a fresh run'
    expected = [snapshot['repository'], str(snapshot['pr']), snapshot['head_sha'], snapshot['policy_sha'], snapshot['base_ref']]
    if latest.get('head_sha') == snapshot['head_sha'] and bound[:5] != expected and bound[:3] + bound[4:5] == expected[:3] + expected[4:]:
        # The dispatcher re-runs every open PR when the config tip moves.
        return (f"{name}: the config branch moved after this run; a fresh run is dispatched automatically (if none arrives: "
                f"`gh workflow run factory.yml --repo {snapshot['repository']} --ref {config['config_branch']} "
                f"-f pr={snapshot['pr']} -f retry=true`)")
    if latest.get('head_sha') != snapshot['head_sha'] or bound[:5] != expected:
        return name + ': bound to another head, target branch or config revision; wait for the fresh run'
    record = bypass_record(latest)
    if record is not None:
        problem = authentic_bypass(gh, latest, record, config, snapshot)
        return problem and f'{name}: {problem}'
    if name == branches.SENIOR:
        reviewed = engine.receipt(latest).get('snapshot') or {}
        if (reviewed.get('handoff'), reviewed.get('feedback_digest')) != (snapshot['handoff'], snapshot['feedback_digest']):
            return name + ': handoff or human feedback changed after the review; wait for the fresh run'
        if reviewed.get('task_pin') != snapshot['task_pin']:
            # The PR's work-order issue was edited and approved again after the review.
            return name + ': the work-order issue changed after the review; re-run the pipeline for a fresh review'
    return None


def verify(gh, pr, config, policy, base):
    """The PR's state and every reason not to merge it onto the current tip of `base`."""
    snapshot, _, _ = session.pr_state(gh, pr, config, policy, base)
    head = snapshot['head_sha']
    problems = ['PR is a draft'] if snapshot['draft'] else []
    if not contains(gh, REPOSITORY, snapshot['base_sha'], head):
        problems.append(engine.behind(base))
    runs = gh.pages(f'/repos/{session.REPOSITORY}/commits/{head}/check-runs?filter=all', 'check_runs')
    problems += [p for p in (check_problem(gh, runs, name, snapshot, config)
                             for name in branches.parse(config).required_checks(base)) if p]
    unresolved = unresolved_threads(gh, pr)
    if unresolved:
        problems.append(f'{unresolved} unresolved review thread(s)')
    return snapshot, problems


def lock_ref(base):
    return f'tags/factory-merge-lock--{base}'


def merge(gh, pr, dry_run=False, base=None):
    """Human merge of exactly the verified head onto exactly the verified tip of a gated validation branch;
    never run by a model."""
    config, policy, user = session.control(gh)
    model = branches.parse(config)
    ref = gh.request('GET', f'/repos/{session.REPOSITORY}/pulls/{pr}')['base']['ref']
    require(base in (None, ref), f'PR #{pr} targets {ref}, not {base}')
    require(model.level(ref) != 'production', f'PR #{pr} targets the production branch {ref}: merge production PRs on GitHub')
    require(model.gated(ref), f'PR #{pr} targets {ref}, which is not a gated validation branch; session.py merge does not merge it')
    base = ref
    snapshot, problems = verify(gh, pr, config, policy, base)
    head, base_sha = snapshot['head_sha'], snapshot['base_sha']
    verdict = {'pr': pr, 'head_sha': head, 'base_ref': base, 'base_sha': base_sha, 'policy_sha': policy,
               'mergeable': not problems, 'problems': problems}
    if dry_run:
        return verdict
    require(not problems, 'not merged: ' + '; '.join(problems))
    # GitHub pins only the head of a merge, never its base: merges into one branch through this helper are
    # serialized by a ref that GitHub creates atomically, and fully re-validated while it is held.
    lock = lock_ref(base)
    release = f'gh api -X DELETE repos/{session.REPOSITORY}/git/refs/{lock}'
    try:
        gh.request('POST', f'/repos/{session.REPOSITORY}/git/refs', {'ref': 'refs/' + lock, 'sha': base_sha})
    except Blocked:
        raise Blocked(f'merge lock refs/{lock} is held or could not be created; nothing was merged. '
                      f'If no merge is running, remove it with: {release}') from None
    unknown = (f'merge outcome of PR #{pr} unknown; the lock stays so nobody merges against an unverified {base}. '
               f'Check PR #{pr}: once it is merged (verify {base}) or certainly not merged, remove the lock with: {release}')
    keep, released = False, False
    try:
        require(session.tip(gh, base) == base_sha and session.tip(gh, model.config_branch) == policy,
                f'{base} or the config branch moved before the merge; nothing was merged')
        again, still = verify(gh, pr, config, policy, base)
        require(again['head_sha'] == head and not still,
                'the PR, its checks or threads changed before the merge; nothing was merged' + ''.join('; ' + p for p in still))
        # From the merge request on, only GitHub's confirmation or refusal may release the lock:
        # without one (no answer, failed read-back, abort) GitHub may still merge against this tip.
        keep = True
        try:
            outcome = gh_merge(pr, head)
            merged = gh.request('GET', f'/repos/{session.REPOSITORY}/pulls/{pr}')
        except BaseException:
            raise Blocked(unknown) from None
        if merged.get('merged') is not True:
            if outcome != 'refused':
                raise Blocked(unknown)
            keep = False
            raise Blocked(f'GitHub refused the merge (changed head, conflict or permission); nothing was merged; inspect PR #{pr}')
        keep = False
        commit = merged.get('merge_commit_sha') or ''
        require(re.fullmatch('[0-9a-f]{40}', commit), f'GitHub did not report the merge commit; inspect PR #{pr}')
        parents = [p['sha'] for p in gh.request('GET', f'/repos/{session.REPOSITORY}/commits/{commit}')['parents']]
    finally:
        if not keep:
            try:
                gh.request('DELETE', f'/repos/{session.REPOSITORY}/git/refs/{lock}')
                released = True
            except Blocked:
                pass
    # With the lock held, only a merge outside this helper (the manual bypass) can change the base.
    exact = parents == [base_sha, head]
    note = ('every required check was verified for exactly this head, target tip and config revision' if exact else
            f"WARNING: {base} was `{(parents or ['unknown'])[0]}` at merge time (a merge outside session.py merge); "
            'this combination was never tested')
    gh.request('POST', f'/repos/{session.REPOSITORY}/issues/{pr}/comments', {'body':
               f"Merged by {user['login']} with `session.py merge`: head `{head}` onto {base} `{base_sha}` as `{commit}`; {note}."})
    require(exact, f'merged as {commit}, but {base} moved outside session.py merge; verify {base} before the next merge')
    require(released, f'merged as {commit}, but the merge lock was not released; remove it with: {release}')
    return {**verdict, 'merged': True, 'merge_commit_sha': commit}
