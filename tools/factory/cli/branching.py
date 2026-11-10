"""Branch commands of the factory CLI: config PRs for the branch list, the control branch, promotions, `factory update`
and the branch diagram.

Branch names, gates, routing and review modes come only from factory/config.json at the pinned config branch tip
(ctx.model). Config PRs change only that file (branches.edited) and replace a branch of their own only after
confirmation, with --force-with-lease; promotions and updates never push a listed branch, never force-push, never
delete and never merge a pull request.
"""
from __future__ import annotations

import html
import json
import shlex
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.

import branches
import checkouts
import commands
import common
from common import Blocked, git, is_ancestor, out, require, say, warn
import session
import workorders

CONFIG = branches.CONFIG
DIAGRAM = 'docs/factory-branches.md'
PAGE = 'branches.html'
NAME_CLASS, MUTED_CLASS = ' class="name"', ' class="muted"'
UNGATED = 'not gated'  # the SVG's own last line of an ungated validation box: no arrow ever runs inside a box


def local_tip(repo, name):
    found = git(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}^{{commit}}', check=False)
    return found.stdout.decode().strip() if found.returncode == 0 else None


# --- config PRs (only factory/config.json, into a production branch) --------------------------------

def settings_step(branch):
    return (f'Apply the repository settings from a clean checkout of `{branch}`: `python3 tools/factory/settings.py diff`, '
            'then `python3 tools/factory/settings.py apply`.')


def create_step(ctx, name, source):
    repository = ctx.config['repository']
    return (f'Create `{name}` on GitHub from the tip of `{source}` before applying the settings: `gh api '
            f'repos/{repository}/git/refs -f ref=refs/heads/{name} -f sha="$(gh api repos/{repository}/git/ref/heads/'
            f'{source} --jq .object.sha)"`.')


def proposed(repo, sha, tip, after):
    parents = out(repo, 'rev-list', '--parents', '-n', '1', sha).split()[1:]
    return (parents == [tip] and out(repo, 'diff', '--name-only', '--no-renames', tip, sha) == CONFIG
            and commands.blob(repo, sha, CONFIG) == after)


def propose(ctx, change, title, slug, summary, steps, target=None):
    """A config PR from the tip of a production branch (default: the config branch) that changes only
    factory/config.json; maintainer approvals and a merge on GitHub decide it. A branch left by an earlier attempt is
    reused when it holds exactly this proposal and replaced only after confirmation; an open PR of it is reported and
    left alone."""
    name, candidate = ctx.model.config_branch, ctx.candidate
    target = target or name
    branch = f'{ctx.login}/config-{slug}'
    tips = ctx.tips(target, branch)
    require(target in tips, f'{target} is not on GitHub')
    tip, existing, replace = tips[target], tips.get(branch), None
    before = commands.blob(candidate, tip, CONFIG)
    require(before is not None, f'{target} has no {CONFIG}')
    try:
        after = branches.edited(before.decode('utf-8'), change).encode('utf-8')
    except Blocked as exc:
        raise Blocked(f'{CONFIG} on {target}: {exc}') from None
    if after == before:
        say(f'{CONFIG} on {target} already says this; nothing to propose.')
        return 0
    pull = commands.open_pull_for(ctx, branch) if existing else None
    if pull:
        number, into = pull['number'], (pull.get('base') or {}).get('ref')
        if pull.get('draft'):  # e.g. session.py left it a draft when its verification failed
            say(f'Pull request #{number} of {branch} into {into} is open as a draft, and its production check fails '
                f'while it is: {common.printable(pull.get("html_url", ""), 300)}. Mark it ready yourself: `gh pr ready '
                f'{number} --repo {ctx.config["repository"]}`.')
            return 1
        say(f'Pull request #{number} of {branch} into {into} is already open: '
            f'{common.printable(pull.get("html_url", ""), 300)}. It is left unchanged; close it to propose something else.')
        return 0
    commands.show_diff(CONFIG, before, after)
    if existing and not proposed(candidate, existing, tip, after):
        say(f'Branch {branch} exists on GitHub without an open pull request and holds something else:')
        say(common.printable(out(candidate, 'log', '--oneline', f'{tip}..{existing}'), 4000))
        require(common.ask(f'Replace {branch} with this proposal?'), 'nothing proposed')
        replace = existing
    url = checkouts.github_url(ctx.config)
    with checkouts.scratch('config-') as scratch:
        objects = [checkouts.objects_dir(candidate), checkouts.objects_dir(ctx.control)]
        if existing and not replace:
            repo = checkouts.materialize(scratch / 'repo', existing, origin=url, branch=branch, objects=objects)
            say(f'Reusing {branch} ({existing[:12]}): it already holds exactly this proposal.')
        else:
            repo = checkouts.materialize(scratch / 'repo', tip, origin=url, branch=branch, objects=objects)
            common.replace_file(repo, CONFIG, after)
            oid = out(repo, 'hash-object', '-w', '--no-filters', '--', CONFIG)  # byte-exact, no attribute conversion
            git(repo, 'update-index', '--cacheinfo', f'100644,{oid},{CONFIG}')
            git(repo, *ctx.identity(), 'commit', '--quiet', '-m', title)
            require(out(repo, 'diff', '--name-only', '--no-renames', tip, 'HEAD') == CONFIG,
                    'a config PR may change only factory/config.json')
            sha = checkouts.head(repo)
            lease = [f'--force-with-lease=refs/heads/{branch}:{replace}'] if replace else []
            git(repo, 'push', '--quiet', *lease, url, f'HEAD:refs/heads/{branch}', network=True)
            say(f'Pushed {branch} ({sha[:12]}).')
            ctx.tips(branch)
        into = f'the config branch `{name}`' if target == name else f'the production branch `{target}`'
        body = scratch / 'body.md'
        body.write_text(f'{summary}, proposed with `factory`.\n\nOnly `{CONFIG}` changes (its `branches` and '
                        '`config_branch` values, checked by `tools/factory/branches.py`). This is a config PR '
                        f'into {into}: it needs approving reviews from {ctx.model.work_order_approvals} maintainer '
                        f'account{"" if ctx.model.work_order_approvals == 1 else "s"} at its current head, `/bypass` '
                        'does not apply, and a maintainer merges it on GitHub. It cannot carry `docs/factory-branches.md`: '
                        'regenerate the diagram with `factory branches` in a later change.\n\nOwner steps after the merge:\n\n'
                        + ''.join(f'{n}. {step}\n' for n, step in enumerate(steps, 1)))
        # No --task: a config PR has no advisory preflight; maintainer approvals and factory/deterministic decide.
        created = commands.session_submit(ctx, repo, None, title, body, base=target)
    if created:
        say(commands.approvals(ctx.model) + ' The owner steps are in the pull request.')
    return 0 if created else 1


def add_validation(ctx, name, gate, kinds):
    model = ctx.model
    verb = 'change' if name in model.validation else 'add'
    steps = [] if verb == 'change' else [create_step(ctx, name, model.default_branch)]
    steps.append(settings_step(model.config_branch))
    if verb == 'add':
        steps.append(f'Bring the config branch into it: `factory update {name}` in the candidate, then push it.')
    if kinds:
        steps.append(f'New work of kind {", ".join(kinds)} goes to `{name}`; open pull requests keep their target.')
    summary = f'{verb.capitalize()} validation branch `{name}` (gate `{gate}`, kinds: {", ".join(kinds) or "none"})'
    return propose(ctx, lambda config: branches.with_validation(config, name, gate, kinds),
                   f'factory(config): {verb} validation branch {name}', f'{verb}-{name}', summary, steps)


def add_production(ctx, name, review):
    model = ctx.model
    verb = 'change' if name in model.production else 'add'
    steps = [] if verb == 'change' else [create_step(ctx, name, model.config_branch)]
    steps.append(settings_step(model.config_branch))
    if verb == 'add':
        steps.append(f'Promote into it with `factory promote <validation branch> --to {name}`.')
    if review != 'no':
        steps.append(f'The AI review of a promotion into `{name}` starts when a maintainer comments `/review` on it'
                     + (' and must pass before the merge.' if review == 'maintainer-manual' else '; it is optional.'))
    summary = f'{verb.capitalize()} production branch `{name}` (review `{review}`)'
    return propose(ctx, lambda config: branches.with_production(config, name, review),
                   f'factory(config): {verb} production branch {name}', f'{verb}-{name}', summary, steps)


def named_by_default(ctx):
    """The config branch that factory/config.json on the default branch names: the dispatcher and the installer start
    there, and branches.follow takes one hop only."""
    default = ctx.model.default_branch
    raw = commands.blob(ctx.candidate, ctx.tip(default), CONFIG)
    try:
        return json.loads(raw)['config_branch']
    except (TypeError, ValueError, KeyError):
        raise Blocked(f'{CONFIG} on the default branch {default} is missing or not valid') from None


def bring_back(ctx):
    model = ctx.model
    return (f'bring the previous change into {model.default_branch} first: `factory promote {model.default_branch} '
            f'--to {model.config_branch}`')


def remove(ctx, name):
    model = ctx.model
    level = model.level(name)
    require(level, f'{name} is not a listed branch ({", ".join(model.names)})')
    if name != model.config_branch:  # branches.without refuses the config branch itself
        require(named_by_default(ctx) != name, f'{CONFIG} on the default branch {model.default_branch} still names {name} '
                f'as the config branch, so the factory still starts from it: {bring_back(ctx)}, then remove {name}')
    steps = [settings_step(model.config_branch) + f' The ruleset of `{name}` is retired.',
             f'factory never deletes branches: keep `{name}` on GitHub or delete it yourself.',
             f'Devices whose control checkout follows `{name}`: `factory use branch {model.config_branch}`.']
    if level == 'validation' and model.validation[name]['kinds']:
        steps.insert(0, f'Its kinds ({", ".join(model.validation[name]["kinds"])}) move to the default branch '
                        f'`{model.default_branch}`; open pull requests into `{name}` are no longer gated.')
    return propose(ctx, lambda config: branches.without(config, name), f'factory(config): remove {level} branch {name}',
                   f'remove-{name}', f'Remove {level} branch `{name}` from the branch list', steps)


def set_config(ctx, name):
    """Two config PRs: first into `name` (its own config.json names it), then into the current config branch. Once
    both are merged, the dispatcher, the installer and every device follow the change (branches.follow)."""
    model = ctx.model
    old = model.config_branch
    require(model.level(name) == 'production', f'{name} is not a listed production branch; add it first with '
            f'`factory add production branch {name} --review <mode>`')
    if name == old:
        say(f'{name} is already the config branch; nothing to propose.')
        return 0
    named = named_by_default(ctx)
    require(named == old, f'{CONFIG} on the default branch {model.default_branch} still names the config branch {named}, '
            f'so a further change would need two hops: {bring_back(ctx)}')
    tips = ctx.tips(old, name)
    require(old in tips and name in tips, f'{old} and {name} must both exist on GitHub')
    found = drift(ctx.candidate, tips[old], tips[name], old, name)
    require(not found, f'{name} cannot become the config branch yet, it would roll the policy back: ' + '; '.join(found)
            + f'. Bring {old} into a validation branch and promote it into {name}: if <V> does not contain {old} yet, '
            f'`factory promote <V> --to {old}` merges {old} into <V> (push it); then `factory promote <V> --to {name}`; '
            'then retry')
    repository = ctx.config['repository']
    slug = lambda target: f'set-config-{name}-into-{target}'
    steps = [f'Right before merging, run `factory set config branch {name}` again: it reuses both pull requests and refuses '
             f'if `{old}` changed since. Merge the config PR into `{name}` (branch `{ctx.login}/config-{slug(name)}`) first: '
             f'`{name}` then names itself as the config branch.',
             f'Then merge the config PR into `{old}` (branch `{ctx.login}/config-{slug(old)}`): from then on the '
             f'dispatcher, the installer and every device follow `{name}`.',
             settings_step(name) + f' Do it right away: the environments `factory-control` and `factory-promotion` '
             f'then allow only `{name}`, and until then factory jobs fail at them.',
             f'Change the WIF rule (`ref`, `workflow_ref`) to `refs/heads/{name}` and run the WIF smoke on `{name}`.',
             f'Bring the change into the validation branches with the next `factory promote <validation branch> --to {name}` '
             f'(it merges `{name}` into them).',
             f'Devices keep working and take their rules from `{name}`; a device whose control checkout runs `{old}` may '
             f'switch with `factory use branch {name}`.',
             f'Re-run the open pull requests on `{name}`, since their checks are bound to `{old}`: `gh pr list --repo '
             f"{repository} --state open --limit 1000 --json number --jq '.[].number' | xargs -I{{}} gh workflow run "
             f'factory.yml --repo {repository} --ref {name} -f pr={{}} -f retry=true`, and the production checks of the '
             'pull requests into ' + ', '.join(f'`{p}`' for p in model.production) + ': '
             + '; '.join(f"`gh pr list --repo {repository} --state open --base {p} --limit 1000 --json number --jq "
                         f"'.[].number' | xargs -I{{}} gh workflow run factory-promotion.yml --repo {repository} --ref {name} "
                         "-f pr={}`" for p in model.production)
             + f'. The first push to `{name}` (for example a merged promotion) re-runs them too.']
    change = lambda config: branches.with_config_branch(config, name)
    for target, summary in ((name, f'Make `{name}` name itself as the config branch (first of two config PRs that make '
                                   f'it the config branch instead of `{old}`)'),
                            (old, f'Make `{name}` the config branch instead of `{old}` (second of two config PRs; the '
                                  f'one into `{name}` merges first)')):
        code = propose(ctx, change, f'factory(config): set config branch {name} on {target}', slug(target), summary,
                       steps, target=target)
        if code:
            return code
    return 0


# --- the control branch of this device ---------------------------------------------------------------

def use(ctx, name):
    """Only a clean control checkout is switched, and only by switch and fast-forward, never reset: factory never
    deletes files there."""
    model, control, config = ctx.model, ctx.control, ctx.config
    level = model.level(name)
    require(level, f'{name} is not a listed production or validation branch; listed: {", ".join(model.names)}')
    with common.Lock(common.STATE_DIR / 'locks/control.lock', 'the control checkout'):
        try:
            session.clean_tree(control, session.identity(control, config))
        except Blocked as exc:
            raise Blocked(f'control checkout {control}: {exc}. factory switches it only when it is clean and never deletes '
                          'files there; remove or revert the named file yourself, then retry') from None
        tips = checkouts.fetch(control, config, name)
        require(name in tips, f'{name} is not on GitHub yet')
        remote, local = tips[name], local_tip(control, name)
        require(not local or is_ancestor(control, local, remote), f'the control checkout has own commits on {name}; '
                'recreate it with the installer')
        if checkouts.current_branch(control) != name:
            git(control, 'switch', '--quiet', *([name] if local else ['--no-track', '-c', name, remote]))
        if checkouts.head(control) != remote:
            git(control, 'merge', '--ff-only', '--quiet', remote)
        session.clean_tree(control, remote)
        checkouts.record_branch(name)
    say(f'The control checkout now runs the {level} branch {name} ({remote[:12]}); rules and policy still '
        f'come from the config branch {model.config_branch}. Recorded in {common.CONFIG_FILE}.')
    return 0


# --- promote -----------------------------------------------------------------------------------------

def promote(ctx, source, target=None):
    model = ctx.model
    require(model.level(source) == 'validation', f'{source} is not a listed validation branch '
            f'({", ".join(model.validation)})')
    if target is None:
        require(len(model.production) == 1, 'several production branches are listed; choose one with --to ('
                + ', '.join(model.production) + ')')
        target = next(iter(model.production))
    require(model.level(target) == 'production', f'{target} is not a listed production branch '
            f'({", ".join(model.production)})')
    if model.gate(source) == 'none':
        warn(f'{source} has gate none: factory/production/{target} fails for it unless a maintainer comments /bypass')
    tips = ctx.tips(source, target)
    require(source in tips and target in tips, f'{source} and {target} must both exist on GitHub')
    head, base = tips[source], tips[target]
    if head == base:  # e.g. right after a pushed fast-forward: GitHub opens no pull request without commits
        say(f'{source} on GitHub is at {target} ({base[:12]}): nothing to promote until {source} has new commits.')
        return 0
    again = f'factory promote {source}' + ('' if len(model.production) == 1 else f' --to {target}')
    if not is_ancestor(ctx.candidate, base, head):
        return merge_production(ctx, source, target, head, base, again)
    return open_promotion(ctx, source, target, head, base)


def bring_in(ctx, branch, remote, theirs, message, why, guard=None):
    """Bring the commit `theirs` into the candidate's local `branch`, never pushing; shared by promote's merge-back
    and `factory update`. `remote` is the tip of `branch` on GitHub, None when it is not there.

    Refuses, changing nothing, while the candidate has uncommitted or untracked files (`why` says what needs it clean)
    or the local branch and GitHub's diverged; a local branch behind GitHub counts at GitHub's tip, unpushed local
    commits are kept with a warning. `guard` may refuse before anything changes. Returns ('contained', tip),
    ('fast-forward', sha), ('merged', sha) or ('conflicts', names); a merge stopped on conflicts is left in the
    candidate for the maintainer to resolve."""
    candidate = ctx.candidate
    with ctx.candidate_lock():
        require(not common.changes(candidate), f'{why} in the candidate, which has uncommitted or untracked files: '
                f'commit, stash or remove them (`git -C {shlex.quote(str(candidate))} status`), then retry')
        local = local_tip(candidate, branch)
        require(local or remote, f'{branch} is neither a branch of the candidate nor on GitHub')
        tip = remote or local
        if local and remote and not is_ancestor(candidate, local, remote):
            require(is_ancestor(candidate, remote, local), f'your local {branch} and {branch} on GitHub diverged; '
                    'reconcile them first')
            warn(f'your local {branch} has commits that are not on GitHub yet; they are pushed with it')
            tip = local
        if is_ancestor(candidate, theirs, tip):
            return 'contained', tip
        fast = is_ancestor(candidate, tip, theirs)
        if guard:
            guard(tip, fast)
        if checkouts.current_branch(candidate) != branch:
            git(candidate, 'switch', '--quiet', *([branch] if local else ['--no-track', '-c', branch, remote]))
        if checkouts.head(candidate) != tip:  # a local branch behind GitHub
            git(candidate, 'merge', '--ff-only', '--quiet', tip)
        if fast:
            git(candidate, 'merge', '--ff-only', '--quiet', theirs)
            return 'fast-forward', checkouts.head(candidate)
        merged = git(candidate, *ctx.identity(), 'merge', '--no-ff', '--no-edit', '-m', message, theirs, check=False)
        if merged.returncode:
            return 'conflicts', out(candidate, 'diff', '--name-only', '--diff-filter=U').splitlines()
        return 'merged', checkouts.head(candidate)


def merge_production(ctx, source, target, head, base, again):
    """The production tip is not contained in the validation branch: bring it in in the candidate, never push."""
    candidate = ctx.candidate
    push = f'git -C {shlex.quote(str(candidate))} push origin {source}'
    outcome, value = bring_in(ctx, source, head, base, f'Merge {target} into {source} for promotion',
                              f'{target} must first be merged into {source}')
    if outcome == 'contained':
        say(f'Your local {source} already contains {target}, {source} on GitHub does not. Push it: {push}; then '
            f'run `{again}` again to open or update the promotion PR.')
        return 0
    if outcome == 'conflicts':
        say(f'Merging {target} ({base[:12]}) into {source} stopped on conflicts; the merge is left in {candidate}:')
        for name in value:
            say('  ' + common.printable(name, 300))
        say('Resolve them, `git add` the files and `git commit` (or give up with `git merge --abort`). Then push '
            f'{source} yourself: {push}, and run `{again}` again to open or update the promotion PR.')
        return 1
    if outcome == 'fast-forward':
        say(f'Fast-forwarded {source} to {target} ({value[:12]}) in the candidate: {source} had nothing that {target} '
            'lacks, so no merge commit was needed. Nothing was pushed.')
        say(f'Push it yourself: {push}. {source} then equals {target}: there is nothing to promote until it has new commits.')
        return 0
    say(f'Merged {target} ({base[:12]}) into {source} in the candidate: {value[:12]}. Nothing was pushed.')
    say(f'Check it, push it yourself: {push}; then run `{again}` again to open or update the promotion PR.')
    return 0


def open_promotion(ctx, source, target, head, base):
    """Expects the production tip to be contained in source. Only one promotion into a production branch may be open
    (factory/production passes only then): an open promotion of source itself already carries the new head and its
    checks re-run, so only another one refuses."""
    model, repository = ctx.model, ctx.config['repository']
    pulls = ctx.gh.pages(f'/repos/{repository}/pulls?state=open&base={target}')
    promotions = [pull for pull in pulls if (pull.get('base') or {}).get('ref') == target
                  and (pull.get('head') or {}).get('ref') in model.validation
                  and ((pull.get('head') or {}).get('repo') or {}).get('full_name') == repository]
    others = [pull for pull in promotions if pull['head']['ref'] != source]
    require(not others, f'a promotion into {target} is already open: ' + ', '.join(
        f'#{pull["number"]} ({pull["head"]["ref"]} → {target})' for pull in others) + '; merge or close it first')
    review = model.review(target)
    hint = {'no': f'{target} has no AI review (review: no).',
            'initiated': 'Optional AI review: comment `/review` on the pull request whenever you want it.',
            'maintainer-manual': 'Required AI review: comment `/review` on the pull request when it is ready; '
                                 'factory/senior-review must pass before the merge (or a maintainer `/bypass <reason>`).'}[review]
    if promotions:
        pull = promotions[0]
        say(f'Promotion #{pull["number"]} ({source} → {target}) is already open and now carries {head[:12]}: '
            f'{common.printable(pull.get("html_url", ""), 300)}')
        say(hint)
        return 0
    body = (f'Promotion of `{source}` into `{target}`, opened with `factory promote`.\n\n'
            f'- Head: `{source}` at `{head[:12]}`; `{target}` (`{base[:12]}`) is contained in it.\n'
            f'- `factory/deterministic` runs on every new commit with the rules of the config branch `{model.config_branch}`.\n'
            f'- `factory/production/{target}` passes only while the head is the current tip of `{source}`, `{target}` is '
            'contained in it and this is the only open promotion into it'
            + (', and the AI review of this head has passed' if model.review_required(target) else '')
            + '; a maintainer `/bypass <reason>` records an exception for exactly the current head.\n'
            f'- AI review (`review: {review}`): {hint}\n'
            '- A maintainer merges this pull request on GitHub; `factory` never merges it.\n')
    created = ctx.gh.request('POST', f'/repos/{repository}/pulls',
                             {'title': f'Promote {source} to {target}', 'head': source, 'base': target, 'body': body})
    say(f'Promotion PR #{created["number"]} opened ({source} → {target}): {common.printable(created.get("html_url", ""), 300)}')
    say(hint)
    return 0


# --- factory update ------------------------------------------------------------------------------------------

def merge_result(repo, ours, theirs):
    """The tree a merge of theirs into ours would write, and its conflicted paths, computed in the object store alone:
    no index, no working tree (git merge-tree --write-tree, git 2.38 or later)."""
    result = git(repo, 'merge-tree', '--write-tree', '--name-only', '--no-messages', '-z', ours, theirs, check=False)
    require(result.returncode in (0, 1), 'git merge-tree failed (factory update needs git 2.38 or later): '
            + common.printable(result.stderr.decode(errors='replace').strip()[-600:], 600))
    fields = result.stdout.decode().split('\0')
    return fields[0], [name for name in fields[1:] if name]


def outside_scope(repo, tip, theirs, fast):
    """Paths that bringing theirs into tip would change beyond factory/config.json and docs/work/*.md."""
    tree, conflicted = (theirs, []) if fast else merge_result(repo, tip, theirs)
    changed = [path for path in out(repo, 'diff', '--name-only', '--no-renames', '-z', tip, tree).split('\0') if path]
    return sorted(path for path in {*changed, *conflicted} if not branches.config_change([path]))


def update(ctx, target=None):
    """Bring the config branch tip into a branch of the candidate. Only factory/config.json and docs/work/*.md may
    change; never pushes, never touches a production branch."""
    model, candidate = ctx.model, ctx.candidate
    source = model.config_branch
    target = target or checkouts.current_branch(candidate)
    require(target, 'the candidate has no branch checked out; name the target: `factory update <target-branch>`')
    valid = git(candidate, 'check-ref-format', f'refs/heads/{target}', check=False).returncode == 0
    require(valid and not target.startswith('-'), f'{common.printable(target, 100)!r} is not a valid branch name')
    require(model.level(target) != 'production', f'{target} is a production branch; factory never changes one. Name a '
            f'validation branch ({", ".join(model.validation)}) or your own branch, e.g. an issue branch')
    tips = ctx.tips(source, target)
    require(source in tips, f'the config branch {source} is not on GitHub')
    theirs, quoted = tips[source], shlex.quote(str(candidate))
    validation = model.level(target) == 'validation'

    def guard(tip, fast):
        found = outside_scope(candidate, tip, theirs, fast)
        shown = ', '.join(common.printable(path, 300) for path in found[:20])
        more = f' and {len(found) - 20} more' if len(found) > 20 else ''
        instead = (f'`factory promote {target}` brings all of {source} into it' if validation
                   else f'merge it by hand: `git -C {quoted} merge origin/{source}`')
        require(not found, f'factory update brings only {CONFIG} and docs/work/*.md, but bringing {source} '
                f'into {target} would also change {shown}{more}. Nothing was changed; {instead}')

    outcome, value = bring_in(ctx, target, tips.get(target), theirs, f'Merge {source} into {target} (factory update)',
                              f'{source} is brought into {target}', guard)
    if outcome == 'contained':
        say(f'{target} ({value[:12]}) already contains {source} ({theirs[:12]}): up to date, nothing changed.')
        return 0
    step = (f'Check it, push it yourself: git -C {quoted} push origin {target}' if validation
            else f'{target} is not a listed branch: it goes up with your next `factory submit`.')
    if outcome == 'conflicts':
        say(f'Merging {source} ({theirs[:12]}) into {target} stopped on conflicts; the merge is left in {candidate}:')
        for name in value:
            say('  ' + common.printable(name, 300))
        say('Resolve them, `git add` the files and `git commit` (or give up with `git merge --abort`). Nothing was '
            f'pushed. {step}')
        return 1
    if outcome == 'fast-forward':
        say(f'Fast-forwarded {target} to {source} ({value[:12]}) in the candidate: no new commit. Nothing was pushed.')
    else:
        say(f'Merged {source} ({theirs[:12]}) into {target} in the candidate: merge commit {value[:12]}. Nothing was pushed.')
    say(step)
    return 0


# --- what a new config branch lacks (set config branch) ----------------------------------------------------

def orders_at(repo, sha, accept=workorders.is_order):
    """Regular work-order files of a commit: path -> (mode, blob id)."""
    found = {}
    for record in git(repo, 'ls-tree', '-z', sha, '--', workorders.WORK).stdout.split(b'\0'):
        if not record:
            continue
        info, raw = record.split(b'\t', 1)
        mode, kind, oid = info.decode().split()
        path = raw.decode('utf-8')
        if kind == 'blob' and mode in ('100644', '100755') and accept(path):
            found[path] = (mode, oid)
    return found


def drift(repo, old_tip, new_tip, old, name):
    """What the branch `name` lacks to become the config branch instead of `old`: its factory/config.json must equal
    old's apart from config_branch, and it must hold every docs/work/*.md of old byte-identical."""
    def config(tip, branch):
        try:
            data = json.loads(commands.blob(repo, tip, CONFIG))
        except (TypeError, ValueError):
            data = None
        require(isinstance(data, dict), f'{CONFIG} on {branch} is missing or not valid')
        return data
    ours, theirs = config(old_tip, old), config(new_tip, name)
    keys = sorted(key for key in {*ours, *theirs} - {'config_branch'}
                  if key not in ours or key not in theirs or ours[key] != theirs[key])
    found = [f'{CONFIG} on {name} differs from {old} in ' + ', '.join(keys)] if keys else []
    work = branches.WORK_ORDER.fullmatch
    have, want = orders_at(repo, new_tip, work), orders_at(repo, old_tip, work)
    missing = sorted(workorders.name_of(path) for path in want if path not in have)
    differing = sorted(workorders.name_of(path) for path in want if path in have and have[path][1] != want[path][1])
    found += [f'{name} lacks ' + ', '.join(workorders.path_of(item) for item in missing)] if missing else []
    found += [f'files on {name} differ from {old}: ' + ', '.join(workorders.path_of(item) for item in differing)] if differing else []
    return found


# --- the branch diagram --------------------------------------------------------------------------------

def nodes(model):
    """Diagram boxes per column: feature, validation, production. Each: (id, lines)."""
    validation = [(f'v{i}', [name, f'gate: {entry["gate"]}', 'kinds: ' + (', '.join(entry['kinds']) or 'none')]
                   + (['default branch'] if name == model.default_branch else []))
                  for i, (name, entry) in enumerate(model.validation.items())]
    production = [(f'p{i}', [name, f'review: {entry["review"]}'] + (['config branch'] if name == model.config_branch else []))
                  for i, (name, entry) in enumerate(model.production.items())]
    return [('feature', ['issue branches', 'e.g. 57-csv-export'])], validation, production


def edges(model):
    """(from, to, label, dotted)."""
    feature, validation, production = nodes(model)
    names = dict(zip([key for key, _ in validation], model.validation))
    config = next(key for key, lines in production if lines[0] == model.config_branch)
    found = [('feature', key, 'PR' if model.gated(names[key]) else 'PR, not gated', False) for key, _ in validation]
    found += [(v, p, 'promotion PR', False) for v, _ in validation for p, _ in production]
    found += [(config, key, 'factory update', True) for key, _ in validation]
    return found


def mermaid(model):
    lines = ['flowchart LR']
    for key, text in [item for column in nodes(model) for item in column]:
        lines.append(f'  {key}["{"<br/>".join(text)}"]')
    for start, end, label, dotted in edges(model):
        lines.append(f'  {start} -. {label} .-> {end}' if dotted else f'  {start} -->|{label}| {end}')
    return '\n'.join(lines) + '\n'


def rows(model):
    found = []
    for name in model.names:
        level = model.level(name)
        roles = [role for role, flag in (('default branch', name == model.default_branch),
                                         ('config branch', name == model.config_branch)) if flag]
        rule = f'gate {model.gate(name)}' if level == 'validation' else f'review {model.review(name)}'
        kinds = ', '.join(model.validation[name]['kinds']) if level == 'validation' else ''
        found.append((name, ', '.join([level, *roles]), rule, kinds, ', '.join(model.required_checks(name))))
    return found


def document(model):
    table = ['| Branch | Level | Gate or review | Kinds | Required checks |', '|---|---|---|---|---|']
    table += [f'| `{name}` | {level} | {rule} | {kinds or "–"} | {checks or "–"} |'
              for name, level, rule, kinds, checks in rows(model)]
    return ('# Factory branches\n\nGenerated by `factory branches` from `factory/config.json` on the config branch '
            f'`{model.config_branch}`; do not edit by hand. Work flows from issue branches (`57-<issue title>` for work-order '
            'issue #57) through validation branches into production branches; after a promotion or a config PR, `factory '
            'update` brings the config branch back into every validation branch ([factory-cli.md](factory-cli.md#factory-branches)).'
            '\n\n```mermaid\n' + mermaid(model) + '```\n\n'
            + '\n'.join(table) + '\n')


WIDTH, LINE, PAD, GAP, LANE, BAND = 230, 18, 10, 28, 180, 40  # least box width, text line, padding, box gap, column gap, label band
BOLD = 8.5  # px per character of a 13px bold name: a box grows with a long name (up to 40); the other lines are short


def layout(model):
    """Boxes {key: (x, y, width, height, lines)}, arrows [(class, sx, sy, ex, ey, bend)], labels [(x, y, text)]
    (centred) and the size. Edge labels stand once per column gap in a band above (PRs, promotions) and below
    (factory update) the boxes, so they never overlap however many branches a column lists. Arrows run only in the
    gaps between columns and every line of text stays inside its box, which grows with a long name: `not gated` is the
    last line of its own box, so no arrow ever crosses it. Promotions leave and enter boxes in their upper part, update
    arrows in their lower part, so the two never run together."""
    feature, validation, production = nodes(model)
    names = dict(zip([key for key, _ in validation], model.validation))
    validation = [(key, text + ([] if model.gated(names[key]) else [UNGATED])) for key, text in validation]
    groups = [feature, validation, production]
    wide = max(WIDTH, round(PAD * 2 + BOLD * max(len(text[0]) for items in groups for _, text in items)))
    columns = [20 + i * (wide + LANE) for i in range(3)]
    tall = lambda text: PAD * 2 + LINE * len(text)
    size = lambda items: sum(tall(text) for _, text in items) + GAP * (len(items) - 1)
    body = max(size(items) for items in groups)
    boxes = {}
    for x, items in zip(columns, groups):
        y = BAND + (body - size(items)) / 2
        for key, text in items:
            boxes[key] = (x, y, wide, tall(text), text)
            y += tall(text) + GAP
    arrows, bend = [], LANE / 3
    for start, end, _, dotted in edges(model):
        (x1, y1, _, h1, _), (x2, y2, _, h2, _) = boxes[start], boxes[end]
        share = 0.75 if dotted else 0.5 if start == 'feature' else 0.3
        if dotted:  # backwards: from the config branch's left edge to the validation branch's right edge
            arrows.append(('back', x1, y1 + h1 * share, x2 + wide, y2 + h2 * share, -bend))
        else:
            arrows.append(('edge', x1 + wide, y1 + h1 * share, x2, y2 + h2 * share, bend))
    middle = lambda column: columns[column] + wide + LANE / 2
    labels = [(middle(0), BAND - 14, 'pull requests'), (middle(1), BAND - 14, 'promotion PRs'),
              (middle(1), BAND + body + 26, 'dotted: factory update')]
    return boxes, arrows, labels, (columns[2] + wide + 20, body + 2 * BAND)


def svg(model):
    """Drawn here rather than rendered from the Mermaid source, so the page loads no script."""
    boxes, arrows, labels, (width, height) = layout(model)
    parts = []
    for x, y, wide, tall, text in boxes.values():
        parts.append(f'<rect x="{x}" y="{y:.0f}" width="{wide}" height="{tall}" rx="8"/>')
        parts += [f'<text x="{x + PAD}" y="{y + PAD + LINE * (i + 1) - 5:.0f}"'
                  f'{NAME_CLASS if i == 0 else MUTED_CLASS if item == UNGATED else ""}>{html.escape(item)}</text>'
                  for i, item in enumerate(text)]
    for kind, sx, sy, ex, ey, bend in arrows:
        parts.append(f'<path class="{kind}" d="M {sx:.0f} {sy:.0f} C {sx + bend:.0f} {sy:.0f}, {ex - bend:.0f} {ey:.0f}, '
                     f'{ex:.0f} {ey:.0f}" marker-end="url(#arrow)"/>')
    parts += [f'<text class="label" x="{x:.0f}" y="{y:.0f}">{html.escape(text)}</text>' for x, y, text in labels]
    head = ('<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" '
            'orient="auto-start-reverse"><path class="tip" d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>')
    return (f'<svg viewBox="0 0 {width} {height:.0f}" role="img" aria-label="Factory branches">'
            + head + ''.join(parts) + '</svg>')


def page(model):
    """Self-contained: no script, stylesheet, font or image is loaded from anywhere."""
    cells = ''.join('<tr>' + ''.join(f'<td>{html.escape(value)}</td>' for value in row) + '</tr>' for row in rows(model))
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Factory branches</title><style>'
            ':root{--bg:#fff;--fg:#1f2328;--box:#f6f8fa;--line:#57606a;--muted:#656d76}'
            '@media (prefers-color-scheme: dark){:root{--bg:#0d1117;--fg:#e6edf3;--box:#161b22;--line:#8b949e;--muted:#8b949e}}'
            'body{margin:2rem auto;max-width:960px;padding:0 1rem;background:var(--bg);color:var(--fg);'
            'font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}'
            'svg{width:100%;height:auto}rect{fill:var(--box);stroke:var(--line)}svg text{fill:var(--fg);font-size:13px}'
            'svg text.name{font-weight:600}svg text.muted{fill:var(--muted)}'
            'svg text.label{fill:var(--muted);font-size:11px;text-anchor:middle}'
            '.edge,.back{fill:none;stroke:var(--line);stroke-width:1.5}.back{stroke-dasharray:5 4}.tip{fill:var(--line)}'
            'table{border-collapse:collapse;width:100%}td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}'
            'pre{background:var(--box);padding:1rem;overflow:auto}</style></head><body>'
            f'<h1>Factory branches</h1><p>From <code>factory/config.json</code> on the config branch '
            f'<code>{html.escape(model.config_branch)}</code>. Issue branches reach validation branches by pull '
            'request, validation branches reach production branches by promotion; dotted arrows: <code>factory update</code> '
            'brings the config branch back.</p>'
            + svg(model) + '<h2>Branches</h2><table><tr><th>Branch</th><th>Level</th><th>Gate or review</th><th>Kinds</th>'
            '<th>Required checks</th></tr>' + cells + '</table><h2>Mermaid source</h2><pre>'
            + html.escape(mermaid(model)) + '</pre></body></html>\n')


def open_file(path):
    opener = common.tool('open', required=False) if sys.platform == 'darwin' else None
    if opener:
        subprocess.run([opener, str(path)], check=False, env=common.child_env(), timeout=30)
    else:
        say(f'Open {path} in your browser.')


def diagram(ctx, show=False):
    model, candidate = ctx.model, ctx.candidate
    found = rows(model)
    widths = [max(len(row[i]) for row in found + [('branch', 'level', 'gate/review', 'kinds', 'required checks')])
              for i in range(5)]
    for row in [('branch', 'level', 'gate/review', 'kinds', 'required checks'), *found]:
        say('  '.join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
    say(f'Config branch: {model.config_branch} · default branch: {model.default_branch} · this device runs the factory '
        f'code of: {ctx.branch}')
    data = document(model).encode()
    with ctx.candidate_lock():
        target = common.checked_target(candidate, DIAGRAM)
        if target.is_file() and target.read_bytes() == data:
            say(f'{target} is up to date.')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            common.replace_file(candidate, DIAGRAM, data)
            say(f'Wrote {target}; commit it with your next change.')
    if show:
        path = common.STATE_DIR / PAGE
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(page(model))
        say(f'Wrote {path}')
        open_file(path)
    return 0
